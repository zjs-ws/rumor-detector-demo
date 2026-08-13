"""Deterministic evidence adjudication for RumorBuster.

The general-purpose model extracts evidence records. This module validates them
against URLs observed in retrieval tools and applies a fixed decision table. The
model may explain the decision, but may not override it.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain.tools import ToolRuntime, tool

from .schemas import (
    ClaimContext,
    ClassifierSignal,
    Directness,
    EvidenceDecision,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceStance,
    ExcludedEvidence,
    SourceLevel,
    TemporalRelevance,
)
from .source_policy import normalize_evidence_items

_URL_RE = re.compile(r"https?://[^\s\]\[<>()\"']+")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip().rstrip(".,;:!?，。；：！？"))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


def observed_evidence_urls(messages: list[Any]) -> set[str]:
    """Collect URLs that really appeared in trusted retrieval tool results."""

    allowed: set[str] = set()
    for message in messages:
        if getattr(message, "name", None) not in {
            "task",
            "web_fetch",
            "retrieve_verified_rumors",
        }:
            continue
        allowed.update(normalize_url(url) for url in _URL_RE.findall(_message_text(message)))
    return allowed


def _compare_classifier_label(label: str, verdict: str) -> str:
    expected = {"rumor": "谣言", "non_rumor": "非谣言"}.get(label)
    if expected is None:
        return "uncertain"
    if verdict not in {"谣言", "非谣言"}:
        return "not_comparable"
    return "consistent" if expected == verdict else "conflict"


def _classifier_consistency(
    signal: ClassifierSignal | None,
    verdict: str,
    subclaim_decisions: dict[str, str],
) -> tuple[str, dict[str, str]]:
    by_claim: dict[str, str] = {}
    if signal is not None:
        for item in signal.subclaims:
            if item.status == "unavailable":
                by_claim[item.claim_id] = "unavailable"
            elif item.status != "ok":
                by_claim[item.claim_id] = "uncertain"
            else:
                by_claim[item.claim_id] = _compare_classifier_label(
                    item.mapped_label,
                    subclaim_decisions.get(item.claim_id, verdict),
                )

    if verdict not in {"谣言", "非谣言", "误导"}:
        return "not_comparable", by_claim
    values = set(by_claim.values())
    if "conflict" in values:
        return "conflict", by_claim
    comparable = values & {"consistent", "conflict"}
    if comparable == {"consistent"}:
        return ("consistent" if values == {"consistent"} else "partial"), by_claim
    if by_claim:
        if values == {"not_comparable"}:
            return "not_comparable", by_claim
        return "unavailable_or_uncertain", by_claim
    if signal is None or signal.status not in {"ok", "partial"}:
        return "unavailable_or_uncertain", by_claim
    return _compare_classifier_label(signal.aggregate_label or signal.label, verdict), by_claim


def _group_key(item: EvidenceItem) -> str:
    return item.independent_group.strip().lower() or urlsplit(item.url).netloc.lower()


def _valid_fetch_timestamp(value: str | None) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _eligible_reason(
    item: EvidenceItem,
    allowed_urls: set[str] | None,
    original_url: str | None,
    *,
    enforce_time: bool = True,
) -> tuple[str, str] | None:
    if item.extraction_status != "ok":
        return "extraction_failed", "证据正文或结构化字段提取失败"
    if allowed_urls is not None and normalize_url(item.url) not in allowed_urls:
        return "url_not_observed", "URL未出现在本轮检索工具结果中"
    if allowed_urls is not None and item.provenance == EvidenceProvenance.WEB and item.directness == Directness.DIRECT and not _valid_fetch_timestamp(item.fetched_at):
        return "fetch_not_verified", "网页证据没有合法的正文抓取时间，不能按直接证据参与裁决"
    if original_url and normalize_url(item.url) == normalize_url(original_url):
        return "original_page", "待核验原网页不能作为独立佐证"
    if item.provenance == EvidenceProvenance.KNOWLEDGE_BASE:
        return "rag_not_authoritative", "RAG命中仅是历史相似记录，不能直接决定当前主张"
    if item.directness != Directness.DIRECT:
        return "not_direct", "非直接证据或仅有搜索摘要"
    if item.source_level not in {SourceLevel.A, SourceLevel.B}:
        return "source_too_weak", "来源等级未达到裁决门槛"
    if item.source_level == SourceLevel.A and not item.authority_scope:
        return "authority_mismatch", "A类来源与该主张的法定或专业职权不匹配"
    if enforce_time and item.temporal_relevance == TemporalRelevance.STALE:
        return "stale", "证据对当前主张已过时"
    if enforce_time and item.temporal_relevance == TemporalRelevance.UNKNOWN and not item.current_validity_confirmed:
        return "time_unknown", "证据发布时间或当前有效性无法确认"
    return None


def _threshold(items: list[EvidenceItem]) -> tuple[bool, list[str], str, str]:
    a_items = [item for item in items if item.source_level == SourceLevel.A]
    if a_items:
        return True, [a_items[0].id], "threshold_a", "一条直接、职权匹配且时效有效的A类证据"

    b_groups: dict[str, EvidenceItem] = {}
    for item in items:
        if item.source_level == SourceLevel.B:
            b_groups.setdefault(_group_key(item), item)
    if len(b_groups) >= 2:
        accepted = [item.id for item in list(b_groups.values())[:2]]
        return True, accepted, "threshold_two_b", "两条独立、直接且时效有效的B类证据"
    return False, [], "threshold_not_met", "未达到一条A类或两条独立B类证据的门槛"


def _basic_outcome(
    eligible: dict[EvidenceStance, list[EvidenceItem]],
) -> tuple[str, str, list[str], list[str], str]:
    support_ok, support_ids, support_code, support_reason = _threshold(eligible[EvidenceStance.SUPPORT])
    refute_ok, refute_ids, refute_code, refute_reason = _threshold(eligible[EvidenceStance.REFUTE])

    support_is_a = support_ok and support_code == "threshold_a"
    refute_is_a = refute_ok and refute_code == "threshold_a"
    support_is_two_b = support_ok and support_code == "threshold_two_b"
    refute_is_two_b = refute_ok and refute_code == "threshold_two_b"

    if support_is_a and refute_is_a:
        return (
            "存疑",
            "conflicting",
            support_ids + refute_ids,
            [support_code, refute_code, "conflicting_thresholds"],
            "支持与反驳双方均有直接、职权匹配的A类证据，规则不允许模型自行选边。",
        )
    if support_is_a:
        return (
            "非谣言",
            "high",
            support_ids,
            [support_code, "a_over_lower_sources"],
            f"支持方达到门槛：{support_reason}；A类来源优先于相反方向的B/C/D来源。",
        )
    if refute_is_a:
        return (
            "谣言",
            "high",
            refute_ids,
            [refute_code, "a_over_lower_sources"],
            f"反驳方达到门槛：{refute_reason}；A类来源优先于相反方向的B/C/D来源。",
        )
    if support_is_two_b and refute_is_two_b:
        return (
            "存疑",
            "conflicting",
            support_ids + refute_ids,
            [support_code, refute_code, "conflicting_thresholds"],
            "支持与反驳双方都达到两条独立B类证据门槛。",
        )
    if support_is_two_b:
        return "非谣言", "medium", support_ids, [support_code], f"支持方达到门槛：{support_reason}。"
    if refute_is_two_b:
        return "谣言", "medium", refute_ids, [refute_code], f"反驳方达到门槛：{refute_reason}。"
    return (
        "证据不足",
        "insufficient",
        [],
        [support_code, refute_code],
        f"支持方：{support_reason}；反驳方：{refute_reason}。",
    )


def decide_evidence(
    *,
    evidence: list[EvidenceItem | dict[str, Any]],
    classifier_signal: ClassifierSignal | dict[str, Any] | None = None,
    allowed_urls: set[str] | None = None,
    original_url: str | None = None,
    claim_context: ClaimContext | dict[str, Any] | None = None,
    materially_mixed_claims: bool = False,
    enforce_time: bool = True,
    enforce_independence: bool = True,
) -> EvidenceDecision:
    """Apply RumorBuster's fixed evidence decision table."""

    if allowed_urls is not None:
        allowed_urls = {normalize_url(url) for url in allowed_urls}

    parsed: list[EvidenceItem] = []
    excluded: list[ExcludedEvidence] = []
    for index, raw in enumerate(evidence):
        try:
            parsed.append(raw if isinstance(raw, EvidenceItem) else EvidenceItem.model_validate(raw))
        except Exception as exc:
            item_id = raw.get("id", f"invalid-{index + 1}") if isinstance(raw, dict) else f"invalid-{index + 1}"
            excluded.append(
                ExcludedEvidence(
                    evidence_id=item_id,
                    reason_code="invalid_schema",
                    explanation=f"证据字段非法：{exc}",
                )
            )

    context = None
    if claim_context is not None:
        try:
            context = claim_context if isinstance(claim_context, ClaimContext) else ClaimContext.model_validate(claim_context)
        except Exception:
            context = None

    parsed, time_errors = normalize_evidence_items(
        parsed,
        context,
        enforce_time=enforce_time,
        merge_independence=enforce_independence,
    )

    signal = None
    if classifier_signal is not None:
        try:
            signal = classifier_signal if isinstance(classifier_signal, ClassifierSignal) else ClassifierSignal.model_validate(classifier_signal)
        except Exception:
            signal = ClassifierSignal(status="unavailable")

    eligible: dict[EvidenceStance, list[EvidenceItem]] = defaultdict(list)
    for item in parsed:
        if item.id in time_errors:
            code = time_errors[item.id]
            explanations = {
                "invalid_date": "证据发布时间格式非法",
                "future_date": "证据发布时间晚于当前日期",
                "stale_current_status": "当前状态类主张不能仅依赖超过365天且未确认仍有效的证据",
                "time_unknown": "证据发布时间或当前有效性无法确认",
            }
            excluded.append(
                ExcludedEvidence(
                    evidence_id=item.id,
                    reason_code=code,
                    explanation=explanations.get(code, "证据时间字段无法验证"),
                )
            )
            continue
        rejection = _eligible_reason(item, allowed_urls, original_url, enforce_time=enforce_time)
        if rejection:
            code, explanation = rejection
            excluded.append(ExcludedEvidence(evidence_id=item.id, reason_code=code, explanation=explanation))
        else:
            eligible[item.stance].append(item)

    subclaim_decisions: dict[str, str] = {}
    material_subclaims = [item for item in (context.subclaims if context else []) if item.material]
    if len(material_subclaims) > 1:
        outcomes: list[tuple[str, str, list[str], list[str], str]] = []
        for subclaim in material_subclaims:
            scoped: dict[EvidenceStance, list[EvidenceItem]] = defaultdict(list)
            for stance, items in eligible.items():
                scoped[stance] = [item for item in items if subclaim.id in item.claim_ids]
            outcome = _basic_outcome(scoped)
            outcomes.append(outcome)
            subclaim_decisions[subclaim.id] = outcome[0]

        verdicts = {outcome[0] for outcome in outcomes}
        accepted_ids = list(dict.fromkeys(evidence_id for outcome in outcomes for evidence_id in outcome[2]))
        reason_codes = list(dict.fromkeys(code for outcome in outcomes for code in outcome[3]))
        if "存疑" in verdicts:
            verdict, strength = "存疑", "conflicting"
            explanation = "至少一个实质子主张内部存在达到门槛的冲突证据。"
        elif "证据不足" in verdicts:
            verdict, strength = "证据不足", "insufficient"
            accepted_ids = []
            explanation = "至少一个实质子主张没有达到独立证据门槛。"
        elif verdicts == {"非谣言"}:
            verdict = "非谣言"
            strength = "high" if all(outcome[1] == "high" for outcome in outcomes) else "medium"
            explanation = "所有实质子主张均由达到门槛的证据支持。"
        elif verdicts == {"谣言"}:
            verdict = "谣言"
            strength = "high" if all(outcome[1] == "high" for outcome in outcomes) else "medium"
            explanation = "所有实质子主张均由达到门槛的证据反驳。"
        else:
            verdict, strength = "误导", "mixed"
            reason_codes.append("materially_mixed_subclaims")
            explanation = "不同实质子主张分别被支持和反驳，整体表述具有误导性。"
    elif materially_mixed_claims and eligible[EvidenceStance.SUPPORT] and eligible[EvidenceStance.REFUTE]:
        # Deprecated compatibility path for persisted v1 calls. New workflow never sets this flag.
        verdict, strength = "误导", "mixed"
        accepted_ids = [eligible[EvidenceStance.SUPPORT][0].id, eligible[EvidenceStance.REFUTE][0].id]
        reason_codes = ["materially_mixed_subclaims"]
        explanation = "主张包含可分离的真假子主张。"
    else:
        verdict, strength, accepted_ids, reason_codes, explanation = _basic_outcome(eligible)

    if len(material_subclaims) == 1 and not subclaim_decisions:
        subclaim_decisions[material_subclaims[0].id] = verdict

    classifier_consistency, classifier_consistency_by_claim = _classifier_consistency(signal, verdict, subclaim_decisions)

    return EvidenceDecision(
        verdict=verdict,
        strength=strength,
        accepted_evidence_ids=accepted_ids,
        excluded_evidence=excluded,
        reason_codes=reason_codes,
        classifier_consistency=classifier_consistency,
        classifier_consistency_by_claim=classifier_consistency_by_claim,
        explanation=explanation,
        subclaim_decisions=subclaim_decisions,
    )


@tool("assess_evidence")
def assess_evidence_tool(
    runtime: ToolRuntime,
    evidence: list[dict[str, Any]],
    classifier_signal: dict[str, Any] | None = None,
    original_url: str | None = None,
    claim_context: dict[str, Any] | None = None,
) -> str:
    """Return the binding verdict from structured evidence; call once after retrieval."""

    messages = list(runtime.state.get("messages", []))
    decision = decide_evidence(
        evidence=evidence,
        classifier_signal=classifier_signal,
        allowed_urls=observed_evidence_urls(messages),
        original_url=original_url,
        claim_context=claim_context,
    )
    return json.dumps(decision.model_dump(mode="json"), ensure_ascii=False)
