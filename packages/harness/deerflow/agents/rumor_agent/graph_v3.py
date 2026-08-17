"""Explicit LangGraph workflow for RumorBuster V3.

The graph owns routing and fan-out/fan-in. Models may extract, research, review,
and explain, but only deterministic evidence code may assign the final verdict.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Annotated, Any, NotRequired
from urllib.parse import urlsplit

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from deerflow.agents.rumor_agent.claim_router import assess_checkability
from deerflow.agents.rumor_agent.evidence import decide_evidence, derive_decision_status, normalize_url
from deerflow.agents.rumor_agent.rag import format_rag_context, retrieve_rumor_knowledge
from deerflow.agents.rumor_agent.research_plan import build_research_plan, repair_temporality
from deerflow.agents.rumor_agent.schemas import (
    Checkability,
    ClaimContext,
    ClaimDomain,
    ClaimTemporality,
    ClassifierSignal,
    EvidenceItem,
    EvidenceReview,
    KnowledgeRetrievalResult,
    Subclaim,
)
from deerflow.agents.rumor_agent.source_policy import normalize_evidence_items
from deerflow.agents.rumor_agent.timeline import build_timeline
from deerflow.agents.rumor_agent.timeline_research import (
    build_timeline_evidence,
    build_timeline_query,
    parse_fetch_result,
    parse_search_results,
    timeline_candidate_relevant,
)
from deerflow.agents.thread_state import ThreadState

_URL_RE = re.compile(r"https?://[^\s\]<>\)\"']+")
_VERIFY_INTENT_RE = re.compile(r"(?:核验|查证|真假|谣言|可信|是否属实|是真的吗|分析.*网页|读取.*网页)")
_FACTUAL_ASSERTION_RE = re.compile(
    r"(?:不能吃|可以吃|不宜食用|有害|无害|有毒|无毒|致癌|治愈|预防|"
    r"导致|造成|引发|含有|检出|属于|并非|已经|曾经|目前|"
    r"宣布|发布|证实|否认|发生|上涨|下降|超过|达到|"
    r"去世|死亡|受伤|离婚|结婚|辞职|被捕|召回|下架|停产|"
    r"被.{0,20}(?:浸泡|浸|喷洒|注射|添加|处理|污染|下药))"
)
_CLEAR_CONVERSATION_RE = re.compile(
    r"^(?:你好|您好|嗨|谢谢|再见|你是谁|你能做什么|怎么使用|如何使用|"
    r"讲个故事|写(?:一|个|篇)|翻译|润色|总结|起个名字|陪我聊)"
)
_CLEAR_OPINION_RE = re.compile(
    r"(?:我觉得|我认为|在我看来|我感觉|我喜欢|我讨厌|我希望|"
    r"最好看|最难看|太难吃|很无聊|心情(?:很好|不好))"
)
_PLAIN_URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+")
_GENERIC_WEB_REQUEST_RE = re.compile(r"^(?:(?:这个|该|此)\s*)?网页(?:的)?(?:主要)?(?:内容|主张|说法|事实)?$")
_VERIFICATION_SUFFIX_RE = re.compile(
    r"(?:(?:这(?:个|条|种)?说法)?(?:是(?:不)?是|是否)?|这是)?"
    r"(?:谣言|真的|属实|可信)(?:吗|呢)?[？?。！!]*$"
)
_EXCERPT_NORMALIZER_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
_ABSENCE_ONLY_RE = re.compile(
    r"(?:未(?:检索到|找到|发现|提及|显示)|没有(?:检索到|找到|发现|提及)|"
    r"no (?:mention|record|result)|not found)",
    re.IGNORECASE,
)

_DOMAIN_PATTERNS: tuple[tuple[ClaimDomain, re.Pattern[str]], ...] = (
    (
        ClaimDomain.MEDICAL,
        re.compile(
            r"(?:医学|医疗|疾病|病毒|细菌|疫苗|药物|药品|治疗|诊断|临床|医生|医院|健康|癌症|新冠|保健|"
            r"食品安全|食品|食物|水果|农产品|农药|添加剂|食用|不能吃|中毒|有害健康|药水|浸泡)"
        ),
    ),
    (ClaimDomain.LEGAL, re.compile(r"(?:法律|法规|刑法|民法|司法解释|法院|检察院|判决|违法|犯罪|拘留|最高法)")),
    (ClaimDomain.FINANCE, re.compile(r"(?:金融|证券|股票|基金|银行|利率|汇率|央行|证监会|上市公司|财报|期货|保险)")),
    (
        ClaimDomain.SCIENCE,
        re.compile(
            r"(?:科学|物理|化学|生物|天文|气候|论文|实验|研究表明|学术|量子|"
            r"强酸|强碱|氢氧化钠|盐酸|腐蚀|放热|化学灼伤|危险化学品|管道疏通剂|洁厕灵)"
        ),
    ),
    (ClaimDomain.TECHNOLOGY, re.compile(r"(?:软件|硬件|算法|人工智能|芯片|网络安全|操作系统|数据库|编程|技术标准)")),
)

_TEXT_RISK_DIMENSIONS = {
    "emotional_manipulation",
    "exaggeration",
    "absolute_claim",
    "forwarding_pressure",
    "internal_contradiction",
    "possible_common_sense_conflict",
}
_TEXT_RISK_LEVELS = {"none", "low", "medium", "high"}
_VERIFICATION_TARGET_KINDS = {"authority", "number", "date", "causal_claim", "entity"}


def merge_branch_status(existing: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """Merge concurrent branch progress while supporting an explicit turn reset."""
    existing = existing or {}
    new = new or {}
    if new.get("__reset__"):
        return {key: value for key, value in new.items() if key != "__reset__"}
    return {**existing, **new}


class RumorV3State(ThreadState):
    rumor_branch_status: Annotated[dict[str, Any], merge_branch_status]
    v3_rag_result: NotRequired[dict[str, Any] | None]
    v3_web_research: NotRequired[dict[str, Any] | None]
    v3_authority_research: NotRequired[dict[str, Any] | None]
    v3_timeline_research: NotRequired[dict[str, Any] | None]
    v3_supplement_research: NotRequired[dict[str, Any] | None]
    v3_classifier_signal: NotRequired[dict[str, Any] | None]
    v3_evidence_review: NotRequired[dict[str, Any] | None]
    v3_rejected_evidence: NotRequired[list[dict[str, Any]] | None]
    v3_explanation: NotRequired[str | None]
    v3_supplement_count: NotRequired[int]


def make_parallel_sends(state: Mapping[str, Any]) -> list[Send]:
    """Fan out isolated snapshots to the bounded evidence and timeline branches."""
    return [Send(branch, dict(state)) for branch in ("rag", "web", "classifier", "authority", "timeline_research")]


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content) if content else ""


def _valid_observed_at(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.isoformat()


def apply_verified_fetch_provenance(
    research: Mapping[str, Any],
    tool_messages: list[dict[str, Any]],
    *,
    relevance_terms: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Bind fetch timestamps to evidence using actual ``web_fetch`` results.

    Search results and model-generated ``fetched_at`` fields are deliberately
    ignored.  Only a successful structured fetch result can make direct web
    evidence eligible for deterministic adjudication.
    """

    fetch_by_url: dict[str, dict[str, Any]] = {}
    for message in tool_messages:
        if message.get("name") != "web_fetch":
            continue
        content = message.get("content")
        if not isinstance(content, str) or content.lstrip().startswith("Error:"):
            continue
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping) or not str(payload.get("content") or "").strip():
            continue
        document = str(payload.get("content") or "")
        observed_at = _valid_observed_at(payload.get("fetched_at"))
        if observed_at is None:
            observed_at = _valid_observed_at(message.get("observed_at"))
        final_url = str(payload.get("source_url") or payload.get("requested_url") or "")
        metadata = {
            "fetched_at": observed_at,
            "content": document,
            "document_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            "content_type": str(payload.get("content_type") or payload.get("mime_type") or "text/html"),
            "final_url": final_url or None,
        }
        for key in ("source_url", "requested_url"):
            url = payload.get(key)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                fetch_by_url[normalize_url(url)] = metadata

    normalized_relevance_terms = [
        _EXCERPT_NORMALIZER_RE.sub("", term).casefold()
        for term in (relevance_terms or [])
        if _EXCERPT_NORMALIZER_RE.sub("", term)
    ]
    enriched = dict(research)
    evidence: list[Any] = []
    for raw_item in research.get("evidence", []) or []:
        if not isinstance(raw_item, Mapping):
            evidence.append(raw_item)
            continue
        item = dict(raw_item)
        url = item.get("url")
        if isinstance(url, str):
            fetch = fetch_by_url.get(normalize_url(url))
            if fetch is not None:
                item.update(
                    {
                        "fetched_at": fetch.get("fetched_at"),
                        "document_hash": fetch["document_hash"],
                        "content_type": fetch["content_type"],
                        "final_url": fetch["final_url"],
                        "fetch_status": "fetched",
                        "fetch_attempts": [
                            {
                                "url": url,
                                "final_url": fetch["final_url"] or url,
                                "status": "fetched",
                            }
                        ],
                    }
                )
                excerpt = str(item.get("excerpt") or "").strip()
                normalized_excerpt = _EXCERPT_NORMALIZER_RE.sub("", excerpt).casefold()
                normalized_document = _EXCERPT_NORMALIZER_RE.sub("", str(fetch["content"])).casefold()
                if item.get("directness") == "direct" and (
                    not normalized_excerpt or normalized_excerpt not in normalized_document
                ):
                    item["directness"] = "indirect"
                    item["extraction_status"] = "excerpt_unverified"
                elif item.get("directness") == "direct" and normalized_relevance_terms:
                    evidence_text = _EXCERPT_NORMALIZER_RE.sub(
                        "", f"{item.get('title', '')}{excerpt}"
                    ).casefold()
                    if not any(term in evidence_text for term in normalized_relevance_terms):
                        item["directness"] = "indirect"
                        item["extraction_status"] = "claim_mismatch"
                if item.get("stance") == "refute" and _ABSENCE_ONLY_RE.search(
                    f"{item.get('summary', '')} {excerpt}"
                ):
                    item["directness"] = "indirect"
                    item["extraction_status"] = "absence_only"
            else:
                item["fetch_status"] = "not_fetched"
                item["fetch_attempts"] = [
                    {
                        "url": url,
                        "final_url": None,
                        "status": "not_fetched",
                    }
                ]
        evidence.append(item)
    enriched["evidence"] = evidence
    return enriched, sorted(fetch_by_url)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")
_MAX_RESCUE_FETCHES = 2
_MAX_SWEEP_FETCHES = 4
_RESCUE_ELIGIBLE_LEVELS = {"A", "B"}
_NEGATION_RE = re.compile(r"(?:不|没有|并非|无|未|否认|辟谣|不实|假的)")
_rescue_logger = logging.getLogger(__name__)


def _text_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> set[str]:
    """Character n-grams used for deterministic excerpt selection."""
    compact = _EXCERPT_NORMALIZER_RE.sub("", text).casefold()
    grams: set[str] = set()
    for size in sizes:
        grams.update(compact[index : index + size] for index in range(len(compact) - size + 1))
    return grams


def _select_verbatim_excerpt(content: str, anchor_texts: list[str]) -> str | None:
    """Pick the fetched-content sentence that best matches the anchors.

    The selected text is verbatim from ``content`` by construction, so the
    excerpt audit passes.  A sentence is only eligible when it shares at
    least one claim-side bigram, keeping unrelated pages from being quoted.
    """
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(content) if len(sentence.strip()) >= 6]
    if not sentences:
        return None
    anchor_grams = _text_ngrams(" ".join(anchor_texts))
    claim_grams = _text_ngrams(anchor_texts[0]) if anchor_texts else set()
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        grams = _text_ngrams(sentence)
        overlap = len(grams & anchor_grams)
        if overlap and (grams & claim_grams):
            scored.append((overlap, sentence))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1].rstrip("。！？!?；; \n")[:220]


async def rescue_unverified_evidence(
    evidence: list[dict[str, Any]],
    claim_context,
    observed_urls: set[str],
    *,
    max_fetches: int = _MAX_RESCUE_FETCHES,
) -> int:
    """Deterministically fetch and quote A/B evidence the model left unverified.

    Research models frequently claim a page was fetched (or misquote it).
    Instead of trusting them, this bounded step re-fetches up to
    ``max_fetches`` eligible URLs itself and replaces the model excerpt with
    a verbatim sentence selected from the fetched content.  The deterministic
    excerpt audit then passes by construction; the A / two-independent-B
    threshold and all other adjudication rules are unchanged.
    """
    from deerflow.config import get_app_config
    from deerflow.reflection import resolve_variable

    candidates: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if normalize_url(url) not in observed_urls:
            continue
        if item.get("timeline_only") or item.get("provenance") != "web":
            continue
        if item.get("source_level") not in _RESCUE_ELIGIBLE_LEVELS:
            continue
        if item.get("fetch_status") != "fetched":
            # Model claimed a direct fetch it never performed.
            if item.get("directness") != "direct":
                continue
        else:
            # Fetched, but the verbatim excerpt audit downgraded the item.
            if item.get("extraction_status") not in {"excerpt_unverified", "claim_mismatch", "absence_only"}:
                continue
        candidates.append(item)
    if not candidates:
        return 0
    candidates.sort(key=lambda item: item.get("source_level") == "B")

    use = str(get_app_config().get_tool_config("web_fetch").use or "")
    fetch_tool = resolve_variable(use) if use else None
    fetch_fn = getattr(fetch_tool, "invoke", None) or getattr(fetch_tool, "ainvoke", None)
    if fetch_fn is None:
        return 0

    claim_texts = [claim_context.normalized_claim]
    claim_texts.extend(item.text for item in claim_context.subclaims if item.material)
    rescued = 0
    for item in candidates[:max_fetches]:
        url = str(item.get("url") or "")
        raw: str | None = None
        for attempt in range(2):
            try:
                raw = await asyncio.to_thread(fetch_fn, {"url": url})
                break
            except Exception as exc:
                _rescue_logger.warning("rescue fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
                if attempt == 0:
                    await asyncio.sleep(1.0)
        if raw is None:
            continue
        if not isinstance(raw, str) or raw.lstrip().startswith("Error:"):
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        excerpt = _select_verbatim_excerpt(content, claim_texts + [str(item.get("excerpt") or "")])
        if excerpt is None:
            continue
        observed_at = _valid_observed_at(payload.get("fetched_at"))
        if observed_at is None:
            continue
        item.update(
            {
                "fetched_at": str(observed_at),
                "document_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "fetch_status": "fetched",
                "final_url": str(payload.get("source_url") or url),
                "directness": "direct",
                "excerpt": excerpt,
                "summary": excerpt,
                "extraction_status": "ok",
                "fetch_attempts": [
                    {
                        "url": url,
                        "final_url": str(payload.get("source_url") or url),
                        "status": "fetched",
                        "via": "deterministic_rescue",
                    }
                ],
            }
        )
        rescued += 1
    return rescued


async def sweep_observed_candidates(
    claim_context,
    observed_urls: list[str],
    existing_urls: set[str],
    *,
    max_fetches: int = _MAX_SWEEP_FETCHES,
) -> list[dict[str, Any]]:
    """Deterministically fetch observed-but-unused URLs and quote matches.

    Research models frequently pick the wrong document from their own search
    results.  This sweep walks every URL the branches actually observed but
    never turned into usable evidence: it fetches the page, grades the source
    deterministically via the registry, and selects a verbatim claim-matching
    sentence.  The first A-grade hit (or the first two B-grade hits) become
    direct evidence; negated sentences are never adopted as support.
    """
    from deerflow.agents.rumor_agent.schemas import EvidenceItem
    from deerflow.agents.rumor_agent.source_policy import grade_source
    from deerflow.config import get_app_config
    from deerflow.reflection import resolve_variable

    candidates = [url for url in observed_urls if url and normalize_url(url) not in existing_urls]
    if not candidates:
        return []
    use = str(get_app_config().get_tool_config("web_fetch").use or "")
    fetch_tool = resolve_variable(use) if use else None
    fetch_fn = getattr(fetch_tool, "invoke", None)
    if fetch_fn is None:
        return []

    claim_texts = [claim_context.normalized_claim]
    claim_texts.extend(item.text for item in claim_context.subclaims if item.material)
    claim_ids = [item.id for item in claim_context.subclaims if item.material] or ["claim-1"]

    adopted: list[dict[str, Any]] = []
    a_hits = 0
    b_hits = 0
    for url in candidates:
        if a_hits >= 1 or b_hits >= 2 or len(adopted) >= max_fetches:
            break
        try:
            raw = await asyncio.to_thread(fetch_fn, {"url": url})
        except Exception as exc:
            _rescue_logger.warning("sweep fetch failed for %s: %s", url, exc)
            continue
        if not isinstance(raw, str) or raw.lstrip().startswith("Error:"):
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        excerpt = _select_verbatim_excerpt(content, claim_texts)
        if excerpt is None or _NEGATION_RE.search(excerpt):
            continue
        observed_at = _valid_observed_at(payload.get("fetched_at"))
        if observed_at is None:
            continue
        final_url = str(payload.get("source_url") or url)
        item = EvidenceItem.model_validate(
            {
                "id": f"sweep-{len(adopted) + 1}",
                "title": str(payload.get("title") or urlsplit(url).hostname or "Untitled"),
                "url": final_url,
                "publisher": urlsplit(url).hostname or url,
                "stance": "support",
                "source_level": "C",
                "claimed_source_level": None,
                "directness": "direct",
                "authority_scope": False,
                "temporal_relevance": "unknown",
                "current_validity_confirmed": False,
                "fetched_at": str(observed_at),
                "excerpt": excerpt,
                "document_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "fetch_status": "fetched",
                "fetch_attempts": [
                    {"url": url, "final_url": final_url, "status": "fetched", "via": "deterministic_sweep"}
                ],
                "content_type": str(payload.get("content_type") or ""),
                "final_url": final_url,
                "extraction_status": "ok",
                "claim_ids": claim_ids,
                "summary": excerpt,
                "provenance": "web",
            }
        )
        grade = grade_source(item, claim_context)
        verified = grade.verified.value
        if verified == "A":
            a_hits += 1
        elif verified == "B":
            b_hits += 1
        else:
            continue
        item_dict = item.model_dump(mode="json")
        item_dict["source_level"] = verified
        item_dict["authority_scope"] = grade.authority_scope
        item_dict["authority_reason"] = grade.authority_reason or grade.reason
        adopted.append(item_dict)
    return adopted


def _latest_human(state: Mapping[str, Any]) -> object | None:
    for message in reversed(list(state.get("messages", []))):
        if getattr(message, "type", None) == "human":
            return message
    return None


def _claim_candidate(raw_input: str) -> str:
    without_urls = _URL_RE.sub("", raw_input)
    lines = [line.strip() for line in without_urls.splitlines() if line.strip() and not line.strip().startswith(("来源页面：", "来源页面:"))]
    value = " ".join(lines)
    value = re.sub(r"^(?:请)?(?:帮我)?(?:读取并)?(?:核验|查证|分析)(?:以下)?(?:网页内容|说法|言论)?[：:\s]*", "", value)
    value = " ".join(value.split()).strip().strip("：:")[:5000]
    value = _VERIFICATION_SUFFIX_RE.sub("", value).strip("，,；;：: ")
    return "" if _GENERIC_WEB_REQUEST_RE.fullmatch(value) else value


def detect_verification_intent(
    raw_input: str,
    *,
    source_url: str | None,
    initial_claim: str,
) -> tuple[bool, str]:
    """Route explicit requests and declarative public claims into fact-checking.

    RumorBuster is a verification workspace, so users should not need to add a
    magic phrase such as ``请核验`` before a claim.  The guard still keeps clear
    greetings, writing tasks, and personal opinions in normal conversation.
    Ambiguous questions remain conversational unless they contain a strong
    factual assertion marker.
    """
    text = " ".join(raw_input.split()).strip()
    claim = " ".join(initial_claim.split()).strip()
    if source_url:
        return True, "public_url"
    if _VERIFY_INTENT_RE.search(text):
        return True, "explicit_verification"
    if not claim or len(claim) < 4:
        return False, "insufficient_input"
    if _CLEAR_CONVERSATION_RE.search(claim):
        return False, "conversation_request"
    if _CLEAR_OPINION_RE.search(claim):
        return False, "personal_opinion"
    if _FACTUAL_ASSERTION_RE.search(claim):
        return True, "factual_assertion"
    if text.endswith(("?", "？")):
        return False, "general_question"
    # A bare declarative sentence in the dedicated verification workspace is
    # treated as a claim.  Later checkability rules can still return a safe
    # boundary result without starting external evidence collection.
    if len(claim) >= 6:
        return True, "declarative_claim"
    return False, "conversation_or_unclear"


def repair_claim_context(context: ClaimContext) -> ClaimContext:
    """Apply narrow deterministic repairs when extraction leaves a compound claim unsplit."""
    claim = _VERIFICATION_SUFFIX_RE.sub("", context.normalized_claim).strip("，,；;：: ")
    repaired_subclaims = [
        item.model_copy(
            update={
                "text": _VERIFICATION_SUFFIX_RE.sub("", item.text).strip("，,；;：: "),
            }
        )
        for item in context.subclaims
        if _VERIFICATION_SUFFIX_RE.sub("", item.text).strip("，,；;：: ")
    ][:3]

    # A common safety-rumour form bundles a product classification with a
    # consequence claim.  They need independent evidence and may have opposite
    # truth values, so never leave them as one indivisible sentence.
    if (
        len(repaired_subclaims) <= 1
        and "疏通剂" in claim
        and "洁厕灵" in claim
        and "强碱" in claim
        and any(token in claim for token in ("热水", "爆射", "喷溅", "毁容", "灼伤"))
    ):
        repaired_subclaims = [
            Subclaim(
                id="claim-1",
                text="管道疏通剂等强碱类清洁剂接触热水可能剧烈反应、喷溅并造成腐蚀伤害",
                material=True,
            ),
            Subclaim(id="claim-2", text="洁厕灵属于强碱类清洁剂", material=True),
        ]

    domain, reason = detect_claim_domain(claim)
    update: dict[str, Any] = {
        "normalized_claim": claim,
        "subclaims": repaired_subclaims or [Subclaim(id="claim-1", text=claim, material=True)],
    }
    if domain != ClaimDomain.GENERAL.value:
        update.update({"domain": ClaimDomain(domain), "domain_reason": reason})
    return repair_temporality(context.model_copy(update=update))


def detect_claim_domain(text: str) -> tuple[str, str]:
    """Return a guarded domain route; professional keywords cannot be skipped."""
    for domain, pattern in _DOMAIN_PATTERNS:
        match = pattern.search(text)
        if match:
            return domain.value, f"命中受控专业关键词：{match.group(0)}"
    return ClaimDomain.GENERAL.value, "未命中需要专门权威检索的领域关键词"


def _normalize_claim_event_date(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip()[:10]).date()
    except ValueError:
        return None
    return parsed.isoformat() if parsed <= date.today() else None


def sanitize_text_risk_analysis(context: ClaimContext | Mapping[str, Any], raw_input: str) -> ClaimContext | dict[str, Any]:
    """Keep only bounded text clues that can be traced back to the input."""

    return_mapping = not isinstance(context, ClaimContext)
    parsed = context if isinstance(context, ClaimContext) else ClaimContext.model_validate(context)
    risk = parsed.text_risk_analysis
    if risk.status != "completed":
        result = parsed.model_copy(update={"text_risk_analysis": risk.model_copy(update={"status": "unavailable", "authoritative": False})})
        return result.model_dump(mode="json") if return_mapping else result
    haystacks = (raw_input, parsed.normalized_claim)
    signals = []
    for signal in risk.signals[:6]:
        if signal.dimension not in _TEXT_RISK_DIMENSIONS or signal.level not in _TEXT_RISK_LEVELS:
            continue
        spans = [span[:200] for span in signal.spans[:5] if span and any(span in haystack for haystack in haystacks)]
        signals.append(signal.model_copy(update={"spans": spans, "note": signal.note[:300]}))
    valid_ids = {item.id for item in parsed.subclaims}
    targets = []
    for target in risk.verification_targets[:10]:
        text = target.text.strip()
        if target.kind not in _VERIFICATION_TARGET_KINDS or not text or _URL_RE.search(text):
            continue
        targets.append(
            target.model_copy(
                update={
                    "text": text[:300],
                    "claim_ids": [item for item in target.claim_ids if item in valid_ids],
                }
            )
        )
    hints = [hint.strip()[:200] for hint in risk.search_hints[:8] if hint.strip() and not _URL_RE.search(hint)]
    result = parsed.model_copy(
        update={
            "text_risk_analysis": risk.model_copy(
                update={
                    "status": "completed",
                    "signals": signals,
                    "verification_targets": targets,
                    "search_hints": hints,
                    "authoritative": False,
                }
            )
        }
    )
    return result.model_dump(mode="json") if return_mapping else result


def parse_claim_context_response(response: object, *, source_url: str | None, raw_input: str = "") -> dict[str, Any]:
    """Parse a plain-model JSON fallback without trusting prose around it."""

    text = response if isinstance(response, str) else _message_text(response)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("claim extraction response contains no JSON object")
    raw_payload = json.loads(text[start : end + 1])
    if not isinstance(raw_payload, Mapping):
        raise ValueError("claim extraction JSON is not an object")
    payload = dict(raw_payload)
    claim = str(payload.get("normalized_claim") or payload.get("claim") or payload.get("main_claim") or "").strip()
    if not claim:
        raise ValueError("claim extraction JSON contains no claim")
    raw_subclaims = payload.get("subclaims")
    if not isinstance(raw_subclaims, list) or not raw_subclaims:
        raw_subclaims = [{"id": "claim-1", "text": claim, "material": True}]
    normalized_subclaims: list[dict[str, Any]] = []
    for index, item in enumerate(raw_subclaims[:3]):
        if isinstance(item, str) and item.strip():
            normalized_subclaims.append(
                {
                    "id": f"claim-{index + 1}",
                    "text": item.strip(),
                    "material": True,
                }
            )
        elif isinstance(item, Mapping) and str(item.get("text") or "").strip():
            normalized_subclaims.append(
                {
                    "id": str(item.get("id") or f"claim-{index + 1}"),
                    "text": str(item["text"]).strip(),
                    "material": bool(item.get("material", True)),
                }
            )
    if not normalized_subclaims:
        normalized_subclaims = [{"id": "claim-1", "text": claim, "material": True}]
    allowed_temporalities = {item.value for item in ClaimTemporality}
    temporality = str(payload.get("temporality") or ClaimTemporality.UNKNOWN.value)
    if temporality not in allowed_temporalities:
        temporality = ClaimTemporality.UNKNOWN.value
    allowed_domains = {item.value for item in ClaimDomain}
    domain = str(payload.get("domain") or ClaimDomain.UNKNOWN.value)
    if domain not in allowed_domains:
        domain = ClaimDomain.UNKNOWN.value
    normalized_payload = {
        "normalized_claim": claim,
        "subclaims": normalized_subclaims,
        "temporality": temporality,
        "temporality_basis": str(payload.get("temporality_basis") or "model"),
        "event_date": _normalize_claim_event_date(payload.get("event_date")),
        "source_url": source_url,
        "domain": domain,
        "domain_reason": str(payload.get("domain_reason") or "普通 JSON 提取回退"),
        "text_risk_analysis": payload.get("text_risk_analysis") or {"status": "unavailable"},
    }
    context = ClaimContext.model_validate(normalized_payload)
    context = repair_claim_context(context)
    sanitized = sanitize_text_risk_analysis(context, raw_input)
    return sanitized.model_dump(mode="json") if isinstance(sanitized, ClaimContext) else sanitized


def _fallback_claim_context(raw_input: str, original_page: dict[str, Any] | None, source_url: str | None) -> dict[str, Any]:
    claim = _claim_candidate(raw_input)
    if not claim and original_page:
        title = str(original_page.get("title", "")).strip()
        content = str(original_page.get("content", "")).strip()
        claim = " ".join(f"{title} {content[:800]}".split()).strip()
    domain, reason = detect_claim_domain(claim)
    context = ClaimContext(
        normalized_claim=claim[:1000],
        subclaims=[Subclaim(id="claim-1", text=claim[:1000], material=True)] if claim else [],
        temporality=ClaimTemporality.UNKNOWN,
        temporality_basis="unknown",
        source_url=source_url,
        domain=ClaimDomain(domain),
        domain_reason=reason,
    )
    return (repair_claim_context(context) if claim else context).model_dump(mode="json")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _branch_update(status: str, started_at: str, started_clock: float, *, result_count: int = 0, error_code: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "started_at": started_at,
        "finished_at": _iso_now(),
        "duration_ms": round((time.monotonic() - started_clock) * 1000),
        "result_count": result_count,
        "error_code": error_code,
    }


def _set_stage(state: Mapping[str, Any], stage: str, **updates: Any) -> dict[str, Any]:
    workflow = dict(state.get("rumor_workflow") or {})
    trace = list(workflow.get("trace") or [])
    if not trace or trace[-1].get("stage") != stage:
        trace.append({"stage": stage, "at": _iso_now()})
    workflow.update(updates)
    workflow["stage"] = stage
    workflow["trace"] = trace
    return workflow


def merge_research_branches(branches: Mapping[str, Mapping[str, Any] | None]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge strict research payloads and reject URLs not seen by retrieval tools."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    used_urls: set[str] = set()
    for branch_name, branch in branches.items():
        if not isinstance(branch, Mapping):
            continue
        observed = {normalize_url(str(url)) for url in branch.get("observed_urls", []) if str(url).startswith(("http://", "https://"))}
        raw_rejected = branch.get("rejected_evidence", [])
        if isinstance(raw_rejected, list):
            rejected.extend(item for item in raw_rejected if isinstance(item, dict))
        raw_evidence = branch.get("evidence", [])
        if not isinstance(raw_evidence, list):
            rejected.append({"reason_code": "invalid_evidence_list", "explanation": f"{branch_name} evidence字段不是数组"})
            continue
        for index, item in enumerate(raw_evidence):
            if not isinstance(item, dict):
                rejected.append({"evidence_id": f"{branch_name}-{index + 1}", "reason_code": "invalid_schema", "explanation": "证据不是对象"})
                continue
            url = str(item.get("url", ""))
            normalized = normalize_url(url) if url.startswith(("http://", "https://")) else ""
            evidence_id = str(item.get("id") or f"{branch_name}-{index + 1}")
            if not normalized or normalized not in observed:
                rejected.append({"evidence_id": evidence_id, "reason_code": "url_not_observed", "explanation": "URL未出现在该研究分支的搜索或抓取结果中"})
                continue
            if normalized in used_urls:
                rejected.append({"evidence_id": evidence_id, "reason_code": "duplicate_url", "explanation": "同一规范化URL已由另一分支收录"})
                continue
            if evidence_id in used_ids:
                evidence_id = f"{branch_name}-{evidence_id}"
            copy = dict(item)
            copy["id"] = evidence_id
            if branch_name == "timeline":
                copy["timeline_only"] = True
                copy["stance"] = "context"
            used_ids.add(evidence_id)
            used_urls.add(normalized)
            accepted.append(copy)
    return accepted, rejected


def build_evidence_review(claim_context: Mapping[str, Any], evidence: list[dict[str, Any]], *, supplement_count: int) -> dict[str, Any]:
    """Build the critic contract from coverage and a preliminary rule check."""
    coverage: dict[str, str] = {}
    missing: list[str] = []
    conflicts: list[str] = []
    groups: dict[str, int] = {}
    for item in evidence:
        group = str(item.get("independent_group", "")).strip()
        if group:
            groups[group] = groups.get(group, 0) + 1
    for subclaim in claim_context.get("subclaims", []):
        if not isinstance(subclaim, Mapping) or not subclaim.get("material", True):
            continue
        claim_id = str(subclaim.get("id", ""))
        matching = [
            item
            for item in evidence
            if claim_id in item.get("claim_ids", [])
            and not item.get("timeline_only")
            and item.get("stance") in {"support", "refute"}
            and item.get("directness") == "direct"
            and item.get("extraction_status") == "ok"
        ]
        stances = {str(item.get("stance")) for item in matching}
        if not matching:
            coverage[claim_id] = "missing"
            missing.append(claim_id)
        elif {"support", "refute"} <= stances:
            coverage[claim_id] = "conflicting"
            conflicts.append(claim_id)
        else:
            coverage[claim_id] = "covered"
    evidence_urls = {str(item.get("url")) for item in evidence if isinstance(item.get("url"), str) and str(item.get("url")).startswith(("http://", "https://"))}
    preliminary = decide_evidence(
        evidence=evidence,
        allowed_urls=evidence_urls,
        original_url=str(claim_context.get("source_url") or "") or None,
        claim_context=dict(claim_context),
    )
    threshold_gap = preliminary.verdict == "证据不足"
    supplement_needed = (bool(missing) or threshold_gap) and supplement_count < 1
    query = "；".join(str(item.get("text", "")) for item in claim_context.get("subclaims", []) if isinstance(item, Mapping) and item.get("id") in missing)
    if threshold_gap and not query:
        query = f"{claim_context.get('normalized_claim', '')}；补充可抓取正文且能达到裁决门槛的职权匹配A类来源，或不同主体的直接B类来源"
    notes = "证据审查只检查覆盖、冲突和裁决门槛，不生成新证据或最终结论。"
    if threshold_gap:
        notes += " 当前证据虽可能覆盖主张，但尚未达到裁决门槛。"
    return EvidenceReview(
        coverage_by_claim=coverage,
        missing_claim_ids=missing,
        conflict_claim_ids=conflicts,
        duplicate_groups=sorted(group for group, count in groups.items() if count > 1),
        threshold_gap=threshold_gap,
        preliminary_reason_codes=list(preliminary.reason_codes),
        supplement_needed=supplement_needed,
        supplement_query=query[:500] if supplement_needed else "",
        notes=notes,
    ).model_dump(mode="json")


def _safe_boundary_decision(checkability: Mapping[str, Any] | None) -> dict[str, Any]:
    checkability = checkability or {}
    value = str(checkability.get("checkability", "needs_clarification"))
    verdicts = {
        "checkable_later": "暂不可核验",
        "not_publicly_checkable": "不可公开核验",
        "not_a_factual_claim": "非事实性表达",
        "needs_clarification": "需要补充主张",
    }
    return {
        "verdict": verdicts.get(value, "证据不足"),
        "strength": "not_applicable" if value != "checkable_now" else "insufficient",
        "accepted_evidence_ids": [],
        "excluded_evidence": [],
        "reason_codes": [value],
        "classifier_consistency": "not_comparable",
        "classifier_consistency_by_claim": {},
        "explanation": str(checkability.get("reason", "本轮无法进入公开证据核验。")),
        "subclaim_decisions": {},
    }


def _render_report(report: Mapping[str, Any]) -> str:
    decision = report.get("decision") or {}
    claim = report.get("claim") or {}
    risk = claim.get("text_risk_analysis") or {}
    classifier = report.get("classifier_signal") or {}
    lines = [
        "## 谣言检测报告",
        "",
        f"**待检测言论**：{claim.get('normalized_claim') or '未提取到明确主张'}",
        f"**判定结论**：{decision.get('verdict', '证据不足')}",
        f"**证据强度**：{decision.get('strength', 'insufficient')}",
        "",
        "> **规则约束**：最终结论由确定性证据规则生成，研究子 Agent、分类器和解释模型均不能覆盖。",
        "",
        "### 文本风险线索",
        "> 文本风险不等于事实为假。",
    ]
    visible_signals = [item for item in risk.get("signals", []) if isinstance(item, Mapping) and item.get("level") != "none"]
    if visible_signals:
        lines.extend(f"- {item.get('dimension')}（{item.get('level')}）：{'；'.join(item.get('spans') or []) or item.get('note', '')}" for item in visible_signals)
    else:
        lines.append("本轮没有可展示的结构化文本风险线索。")
    lines.extend(
        [
            "",
            "### 微调模型信号",
            f"状态：{classifier.get('status', 'unavailable')}；聚合标签：{classifier.get('aggregate_label') or classifier.get('label', 'uncertain')}。",
            "模型仅依据文本模式分类，没有读取本轮网页证据。",
            "",
            "### 综合分析",
            str(report.get("explanation") or decision.get("explanation", "")),
            "",
            "### 外部证据",
        ]
    )
    evidence = list(report.get("evidence") or [])
    accepted_ids = set(decision.get("accepted_evidence_ids") or [])
    if evidence:
        for item in evidence:
            purpose = "用于裁决" if item.get("id") in accepted_ids else "未用于裁决"
            lines.append(f"- [{item.get('title', '来源')}]({item.get('url', '')}) — {item.get('verified_source_level') or item.get('source_level', 'D')}级，{purpose}：{item.get('summary', '')}")
    else:
        lines.append("本轮没有通过结构与来源校验的外部证据。")
    lines.extend(["", "### 局限", *(f"- {item}" for item in report.get("limitations", []) or ["无额外降级项"])])
    return "\n".join(lines)


class RumorV3Services:
    """Replaceable I/O boundary used by the explicit graph and scripted tests."""

    def __init__(
        self,
        *,
        web_search_enabled: bool,
        web_fetch_enabled: bool,
        classifier_enabled: bool,
        classifier_required: bool = True,
        timeline_enabled: bool = False,
    ):
        self.web_search_enabled = web_search_enabled
        self.web_fetch_enabled = web_fetch_enabled
        self.classifier_enabled = classifier_enabled
        self.classifier_required = classifier_required
        self.timeline_enabled = timeline_enabled

    def capabilities(self) -> dict[str, bool]:
        return {
            "web_search": self.web_search_enabled,
            "web_fetch": self.web_fetch_enabled,
            "classifier": self.classifier_enabled,
            "classifier_required": self.classifier_required,
            "rag": True,
            "authority_research": self.web_search_enabled,
            "evidence_critic": True,
            "timeline_research": self.timeline_enabled and self.web_search_enabled and self.web_fetch_enabled,
            "social_context": False,
        }

    async def fetch_original(self, url: str, config: RunnableConfig) -> dict[str, Any]:
        from deerflow.tools import get_available_tools

        model_name = _model_name()
        tool = next((item for item in get_available_tools(model_name=model_name, subagent_enabled=False) if item.name == "web_fetch"), None)
        if tool is None:
            raise RuntimeError("web_fetch is not configured")
        raw = await asyncio.wait_for(tool.ainvoke({"url": url}), timeout=12)
        if isinstance(raw, str):
            payload = json.loads(raw)
        elif isinstance(raw, Mapping):
            payload = dict(raw)
        else:
            raise ValueError("web_fetch returned an unsupported payload")
        if not payload.get("content"):
            raise ValueError("web_fetch returned no readable content")
        return payload

    async def extract_claim(self, raw_input: str, original_page: dict[str, Any] | None, source_url: str | None, config: RunnableConfig) -> dict[str, Any]:
        fallback = _fallback_claim_context(raw_input, original_page, source_url)
        if not fallback.get("normalized_claim"):
            return fallback
        source_context = ""
        if original_page:
            source_context = f"\n网页标题：{original_page.get('title', '')}\n网页正文：{str(original_page.get('content', ''))[:12000]}"
        prompt = (
            "从输入和已抓取网页中提取一条规范化、可公开核验的事实主张，必要时拆成最多3条实质子主张；"
            "判断时态和专业领域，并提取六类语言风险线索及待核验对象，只分析文本现象，不判断真假。"
            "时态只可为current_status/event_bound/timeless/general/unknown；无时态标记且长期成立的普遍性事实为general；治疗、药物等领域词本身不代表当前状态。"
            "风险维度只能是 emotional_manipulation/exaggeration/absolute_claim/forwarding_pressure/"
            "internal_contradiction/possible_common_sense_conflict；spans必须逐字来自输入；不得生成URL。"
            "domain只能是general/medical/legal/finance/science/technology/unknown。"
            "不要把‘网页主要内容’这类操作指令当成主张。\n"
            f"用户输入：{raw_input[:5000]}{source_context}"
        )
        try:
            model = _chat_model(thinking_enabled=False).with_structured_output(ClaimContext)
            parsed = await asyncio.wait_for(model.ainvoke(prompt, config=config), timeout=16)
            context = parsed if isinstance(parsed, ClaimContext) else ClaimContext.model_validate(parsed)
            context = context.model_copy(
                update={
                    "source_url": source_url,
                    "subclaims": context.subclaims[:3],
                    "event_date": _normalize_claim_event_date(context.event_date),
                }
            )
            context = repair_claim_context(context)
            sanitized = sanitize_text_risk_analysis(context, raw_input)
            context = sanitized if isinstance(sanitized, ClaimContext) else ClaimContext.model_validate(sanitized)
            return context.model_dump(mode="json")
        except Exception:
            try:
                plain_prompt = f"{prompt}\n只输出一个JSON对象，字段必须为：normalized_claim、subclaims、temporality、temporality_basis、event_date、source_url、domain、domain_reason、text_risk_analysis。不得输出Markdown。"
                plain = await asyncio.wait_for(
                    _chat_model(thinking_enabled=False).ainvoke(plain_prompt, config=config),
                    timeout=16,
                )
                return parse_claim_context_response(plain, source_url=source_url, raw_input=raw_input)
            except Exception:
                if not _claim_candidate(raw_input) and original_page:
                    return ClaimContext(
                        normalized_claim="",
                        subclaims=[],
                        temporality=ClaimTemporality.UNKNOWN,
                        source_url=source_url,
                        domain=ClaimDomain.UNKNOWN,
                        domain_reason="URL-only 输入的主张提取不可用，需要用户补充明确主张",
                    ).model_dump(mode="json")
                return fallback

    async def retrieve_rag(self, claim_context: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
        timeout = max(1.0, min(float(os.getenv("RUMOR_RAG_TIMEOUT_SECONDS", "20")), 45.0))
        result = await asyncio.wait_for(
            asyncio.to_thread(retrieve_rumor_knowledge, claim_context, final_k=6),
            timeout=timeout,
        )
        return result.model_dump(mode="json")

    async def research_web(self, claim_context: Mapping[str, Any], config: RunnableConfig, *, supplementary: bool = False, gap_query: str = "") -> dict[str, Any]:
        prompt = _research_prompt(claim_context, authority=False, gap_query=gap_query)
        plan = claim_context.get("research_plan") or {}
        query = str((plan.get("queries") or {}).get("discovery") or claim_context.get("normalized_claim") or "")
        return await _run_research_subagent(
            "web-researcher",
            prompt,
            config,
            timeout=35 if supplementary else 55,
            supplementary=supplementary,
            locked_query=query,
            relevance_terms=[
                str(term)
                for entity in plan.get("entities", [])
                for term in entity.get("evidence_terms", [])
            ],
        )

    async def classify(self, claim_context: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
        from deerflow.agents.rumor_agent.tools import (
            _model_api_style,
            _model_id,
            aggregate_classifier_signal,
            classify_claim_text,
        )

        material = [item for item in claim_context.get("subclaims", []) if isinstance(item, Mapping) and item.get("material", True)][:3]
        if not material and str(claim_context.get("normalized_claim", "")).strip():
            material = [
                {
                    "id": "claim-1",
                    "text": str(claim_context.get("normalized_claim", "")).strip(),
                }
            ]
        try:
            budget = min(20.0, max(1.0, float(os.getenv("RUMOR_MODEL_TIMEOUT_SECONDS", "20"))))
        except ValueError:
            budget = 20.0
        deadline = time.monotonic() + budget
        results: list[dict[str, Any]] = []
        for item in material:
            text = str(item.get("text", "")).strip()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                now = _iso_now()
                result = {
                    "status": "unavailable",
                    "raw_label": None,
                    "mapped_label": "uncertain",
                    "latency_ms": 0,
                    "input_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "request_id": uuid.uuid4().hex,
                    "called_at": now,
                    "usage": {},
                    "error_code": "classifier_budget_exhausted",
                }
            else:
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            classify_claim_text,
                            text,
                            timeout_seconds=remaining,
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    result = {
                        "status": "unavailable",
                        "raw_label": None,
                        "mapped_label": "uncertain",
                        "latency_ms": round(max(0.0, budget - max(remaining, 0)) * 1000),
                        "input_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "request_id": uuid.uuid4().hex,
                        "called_at": _iso_now(),
                        "usage": {},
                        "error_code": "classifier_timeout",
                    }
            results.append(
                {
                    **result,
                    "claim_id": str(item.get("id") or f"claim-{len(results) + 1}"),
                    "text": text,
                }
            )
        payload = aggregate_classifier_signal(results, model_id=_model_id(), api_style=_model_api_style())
        return ClassifierSignal.model_validate(payload).model_dump(mode="json")

    async def research_authority(self, claim_context: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
        plan = claim_context.get("research_plan") or {}
        query = str((plan.get("queries") or {}).get("authority") or "")
        if not query:
            raise RuntimeError("no deterministic authority query is available")
        return await _run_research_subagent(
            "authority-researcher",
            _research_prompt(claim_context, authority=True),
            config,
            timeout=55,
            locked_query=query,
            relevance_terms=[
                str(term)
                for entity in plan.get("entities", [])
                for term in entity.get("evidence_terms", [])
            ],
        )

    async def research_timeline(self, claim_context: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
        from deerflow.tools import get_available_tools

        del config  # Timeline collection is deterministic and does not call a model.
        tools = get_available_tools(model_name=_model_name(), subagent_enabled=False)
        search_tool = next((tool for tool in tools if tool.name == "web_search"), None)
        fetch_tool = next((tool for tool in tools if tool.name == "web_fetch"), None)
        if search_tool is None or fetch_tool is None:
            raise RuntimeError("timeline research requires web_search and web_fetch")

        raw_search = await asyncio.wait_for(
            search_tool.ainvoke(
                {
                    "query": build_timeline_query(claim_context),
                    "max_results": 5,
                }
            ),
            timeout=18,
        )
        candidates = parse_search_results(raw_search, limit=5)
        if not candidates:
            return {
                "status": "insufficient",
                "evidence": [],
                "rejected_evidence": [],
                "observed_urls": [],
                "fetched_urls": [],
                "notes": "传播检索没有返回可抓取页面。",
            }

        async def fetch_candidate(candidate: Mapping[str, Any]) -> dict[str, object] | None:
            try:
                raw = await asyncio.wait_for(
                    fetch_tool.ainvoke({"url": str(candidate.get("url") or "")}),
                    timeout=12,
                )
            except Exception:
                return None
            return parse_fetch_result(raw)

        fetched = await asyncio.gather(*(fetch_candidate(candidate) for candidate in candidates))
        claim_ids = [
            str(item.get("id"))
            for item in claim_context.get("subclaims", [])
            if isinstance(item, Mapping) and item.get("material", True) and item.get("id")
        ][:3]
        evidence: list[dict[str, Any]] = []
        fetched_urls: list[str] = []
        observed_urls = [str(candidate["url"]) for candidate in candidates]
        for candidate, payload in zip(candidates, fetched, strict=True):
            if payload is None:
                continue
            if not timeline_candidate_relevant(
                str(claim_context.get("normalized_claim") or ""),
                candidate.get("title"),
                candidate.get("content"),
                payload.get("title"),
                str(payload.get("content") or "")[:4000],
            ):
                continue
            item = build_timeline_evidence(
                index=len(evidence) + 1,
                search_result=candidate,
                fetch_result=payload,
                claim_ids=claim_ids,
            )
            evidence.append(item)
            fetched_url = str(payload.get("source_url") or candidate["url"])
            fetched_urls.append(fetched_url)
            observed_urls.append(fetched_url)
        return {
            "status": "ok" if evidence else "insufficient",
            "evidence": evidence,
            "rejected_evidence": [],
            "observed_urls": sorted(set(observed_urls)),
            "fetched_urls": sorted(set(fetched_urls)),
            "notes": "传播节点由一次搜索和受限正文抓取确定性生成，不经过模型重写。",
        }

    async def review_evidence(self, claim_context: Mapping[str, Any], evidence: list[dict[str, Any]], config: RunnableConfig) -> dict[str, Any]:
        prompt = (
            "检查以下证据是否覆盖每个子主张、是否答非所问、是否存在支持和反驳冲突。"
            "不得新增URL、来源等级、事实或最终真假，只输出EvidenceReview兼容JSON。\n"
            f"主张：{json.dumps(claim_context, ensure_ascii=False)}\n证据：{json.dumps(evidence, ensure_ascii=False)}"
        )
        result = await _run_text_subagent("evidence-critic", prompt, config, timeout=20)
        try:
            start = result.find("{")
            return EvidenceReview.model_validate(json.loads(result[start:])).model_dump(mode="json")
        except Exception:
            return {}

    async def explain(self, workflow: Mapping[str, Any], config: RunnableConfig) -> str:
        decision = workflow.get("decision") or {}
        rag_context = format_rag_context(workflow.get("rag_result"))
        prompt = (
            "根据给定的文本风险线索、辅助分类信号、历史知识、规则结论和已校验证据，生成简洁中文解释。"
            "不得改变结论，不得添加URL或新事实；不得把语言风险、分类标签或RAG命中写成事实证明；"
            "历史知识只能用于说明相似背景，不能把历史结论复制为当前结论；人物、时间、地点或数量不同时必须指出。"
            "事实说明只能引用给定证据ID。\n"
            f"文本风险：{json.dumps((workflow.get('claim_context') or {}).get('text_risk_analysis'), ensure_ascii=False)}\n"
            f"分类信号：{json.dumps(workflow.get('classifier_signal'), ensure_ascii=False)}\n"
            f"历史知识：\n{rag_context or '无本地知识库命中'}\n"
            f"结论：{json.dumps(decision, ensure_ascii=False)}\n"
            f"证据：{json.dumps(workflow.get('evidence', []), ensure_ascii=False)}"
        )
        try:
            response = await asyncio.wait_for(_chat_model(thinking_enabled=True).ainvoke(prompt, config=config), timeout=20)
            return _URL_RE.sub("", _message_text(response)).strip() or str(decision.get("explanation", ""))
        except Exception:
            return str(decision.get("explanation", ""))

    async def chat(self, raw_input: str, config: RunnableConfig) -> str:
        try:
            response = await asyncio.wait_for(_chat_model(thinking_enabled=True).ainvoke(raw_input, config=config), timeout=20)
            return _message_text(response)
        except Exception:
            return "我可以帮助核验公开、可查证的事实主张。"


def _model_name() -> str:
    from deerflow.config.app_config import get_app_config

    config = get_app_config()
    if not config.models:
        raise ValueError("No chat models are configured")
    return config.models[0].name


def _chat_model(*, thinking_enabled: bool):
    from deerflow.models import create_chat_model

    return create_chat_model(name=_model_name(), thinking_enabled=thinking_enabled)


def _research_prompt(claim_context: Mapping[str, Any], *, authority: bool, gap_query: str = "") -> str:
    subclaims = "\n".join(f"- {item.get('id')}: {item.get('text')}" for item in claim_context.get("subclaims", []) if isinstance(item, Mapping))
    focus = "仅检索与该专业领域职权匹配的官方、监管、学术原始来源。" if authority else "检索公开来源，优先原始来源和能够直接支持或反驳的正文。"
    gap = f"\n补检缺口：{gap_query}" if gap_query else ""
    risk = claim_context.get("text_risk_analysis") or {}
    targets = json.dumps(risk.get("verification_targets", []), ensure_ascii=False)
    hints = json.dumps(risk.get("search_hints", []), ensure_ascii=False)
    plan = claim_context.get("research_plan") or {}
    query_key = "authority" if authority else "discovery"
    locked_query = str((plan.get("queries") or {}).get(query_key) or "")
    authority_targets = json.dumps(plan.get("authority_targets", []), ensure_ascii=False)
    return (
        f"待核验原文：{claim_context.get('normalized_claim', '')}\n子主张：\n{subclaims}\n"
        f"核验目标：{targets}\n搜索提示：{hints}\n受控权威目标：{authority_targets}\n"
        f"系统锁定查询：{locked_query}\n{focus}{gap}\n"
        "web_search 的 query 参数会被系统强制替换为锁定查询，不得绕过。"
        "必须同时寻找支持和反驳材料，不得被文本风险标签预设方向；"
        "不得把未搜到、页面未提及或无关页面作为反驳证据。"
        "direct证据必须提供正文中的连续原文excerpt；无法给出可反查原文时标为indirect或snippet_only。"
        "只返回严格JSON证据，不输出最终真假。"
    )


async def _run_text_subagent(name: str, prompt: str, config: RunnableConfig, *, timeout: int) -> str:
    from deerflow.subagents import SubagentExecutor, get_subagent_config
    from deerflow.tools import get_available_tools

    agent_config = get_subagent_config(name)
    if agent_config is None:
        raise RuntimeError(f"subagent {name} is not registered")
    metadata = config.get("metadata", {}) if isinstance(config, Mapping) else {}
    configurable = config.get("configurable", {}) if isinstance(config, Mapping) else {}
    parent_model = str(metadata.get("model_name") or _model_name())
    executor = SubagentExecutor(
        config=agent_config,
        tools=get_available_tools(model_name=parent_model, subagent_enabled=False),
        parent_model=parent_model,
        thread_id=str(configurable.get("thread_id") or metadata.get("thread_id") or "") or None,
        trace_id=str(metadata.get("trace_id") or uuid.uuid4().hex[:8]),
    )
    result = await asyncio.wait_for(executor._aexecute(prompt), timeout=timeout)
    if getattr(result.status, "value", str(result.status)) != "completed":
        raise RuntimeError(result.error or f"{name} failed")
    return result.result or ""


async def _run_research_subagent(
    name: str,
    prompt: str,
    config: RunnableConfig,
    *,
    timeout: int,
    supplementary: bool = False,
    locked_query: str = "",
    relevance_terms: list[str] | None = None,
) -> dict[str, Any]:
    from dataclasses import replace

    from deerflow.agents.middlewares.rumor_workflow_middleware import parse_research_result
    from deerflow.subagents import get_subagent_config

    agent_config = get_subagent_config(name)
    if agent_config is None:
        raise RuntimeError(f"subagent {name} is not registered")
    if supplementary:
        agent_config = replace(agent_config, timeout_seconds=35, max_tool_calls=3, tool_call_limits={"web_search": 1, "web_fetch": 2})
    # Temporarily replace the registry lookup for the shared runner by directly
    # executing the selected configuration so its strict budgets remain intact.
    from deerflow.subagents import SubagentExecutor
    from deerflow.tools import get_available_tools

    metadata = config.get("metadata", {}) if isinstance(config, Mapping) else {}
    configurable = config.get("configurable", {}) if isinstance(config, Mapping) else {}
    parent_model = str(metadata.get("model_name") or _model_name())
    tools = get_available_tools(model_name=parent_model, subagent_enabled=False)
    if locked_query:
        original_search = next((item for item in tools if item.name == "web_search"), None)
        if original_search is None:
            raise RuntimeError("web_search is not configured")

        async def locked_web_search(query: str = "", max_results: int = 5) -> Any:
            """Run the deterministic research query; model arguments are ignored."""

            del query
            search_input: dict[str, Any] = {"query": locked_query[:500]}
            schema = getattr(original_search, "args_schema", None)
            fields = getattr(schema, "model_fields", {}) if schema is not None else {}
            if "max_results" in fields:
                search_input["max_results"] = min(max(int(max_results), 1), 5)
            return await original_search.ainvoke(search_input)

        locked_tool = StructuredTool.from_function(
            coroutine=locked_web_search,
            name="web_search",
            description="Search using the system-locked fact-check query. The supplied query is ignored.",
        )
        tools = [locked_tool if item.name == "web_search" else item for item in tools]

    executor = SubagentExecutor(
        config=agent_config,
        tools=tools,
        parent_model=parent_model,
        thread_id=str(configurable.get("thread_id") or metadata.get("thread_id") or "") or None,
        trace_id=str(metadata.get("trace_id") or uuid.uuid4().hex[:8]),
    )
    result = await asyncio.wait_for(executor._aexecute(prompt), timeout=timeout)
    if getattr(result.status, "value", str(result.status)) != "completed":
        raise RuntimeError(result.error or f"{name} failed")
    research, rejected = parse_research_result(result.result or "")
    research_payload, fetched_urls = apply_verified_fetch_provenance(
        research.model_dump(mode="json"),
        list(getattr(result, "tool_messages", []) or []),
        relevance_terms=relevance_terms,
    )
    observed_urls: set[str] = set()
    for message in getattr(result, "tool_messages", []) or []:
        content = message.get("content", "") if isinstance(message, Mapping) else ""
        observed_urls.update(_PLAIN_URL_RE.findall(str(content)))
    # Compatibility for older executors: direct source URLs remain unavailable
    # rather than silently trusting the final model text.
    return {
        **research_payload,
        "rejected_evidence": rejected,
        "observed_urls": sorted(observed_urls),
        "fetched_urls": fetched_urls,
    }


def _report_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    workflow = dict(state.get("rumor_workflow") or {})
    original = workflow.get("original_page")
    if isinstance(original, Mapping):
        original = {key: original.get(key) for key in ("source_url", "requested_url", "title", "content_chars", "truncated")}
    return {
        "schema_version": "rumorbuster-report-v3",
        "claim": workflow.get("claim_context"),
        "checkability": workflow.get("checkability"),
        "domain_route": {
            "domain": (workflow.get("claim_context") or {}).get("domain", "unknown"),
            "reason": (workflow.get("claim_context") or {}).get("domain_reason", ""),
        },
        "research_plan_summary": workflow.get("research_plan"),
        "capabilities": workflow.get("capabilities", {}),
        "original_page": original,
        "research_branches": dict(state.get("rumor_branch_status") or {}),
        "rag": workflow.get("rag_result"),
        "classifier_signal": workflow.get("classifier_signal"),
        "evidence": workflow.get("evidence", []),
        "evidence_review": workflow.get("evidence_review"),
        "decision": workflow.get("decision") or _safe_boundary_decision(workflow.get("checkability")),
        "timeline": workflow.get("timeline") or {"timeline_status": "insufficient", "events": [], "note": "没有足够的带日期可追溯事件。"},
        "limitations": workflow.get("degradation_codes", []),
        "workflow_trace": workflow.get("trace", []),
        "explanation": state.get("v3_explanation") or (workflow.get("decision") or {}).get("explanation", ""),
    }


def build_rumor_graph_v3(services: RumorV3Services):
    """Build and compile the explicit V3 graph with replaceable I/O services."""

    async def reset_turn(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        human = _latest_human(state)
        raw_input = _message_text(human) if human is not None else ""
        urls = _URL_RE.findall(raw_input)
        source_url = urls[0].rstrip(".,;:!?，。；：！？") if urls else None
        initial_claim = _claim_candidate(raw_input)
        is_verification, routing_reason = detect_verification_intent(
            raw_input,
            source_url=source_url,
            initial_claim=initial_claim,
        )
        run_id = uuid.uuid4().hex
        workflow = {
            "input_message_id": getattr(human, "id", None),
            "run_id": run_id,
            "stage": "reset_input",
            "raw_input": raw_input,
            "source_url": source_url,
            "initial_claim": initial_claim,
            "is_verification": is_verification,
            "routing_reason": routing_reason,
            "capabilities": services.capabilities(),
            "degradation_codes": [],
            "trace": [{"stage": "reset_input", "at": _iso_now()}],
        }
        return {
            "rumor_workflow": workflow,
            "rumor_report": None,
            "rumor_branch_status": {"__reset__": True},
            "v3_rag_result": None,
            "v3_web_research": None,
            "v3_authority_research": None,
            "v3_timeline_research": None,
            "v3_supplement_research": None,
            "v3_classifier_signal": None,
            "v3_evidence_review": None,
            "v3_rejected_evidence": None,
            "v3_explanation": None,
            "v3_supplement_count": 0,
        }

    def route_after_reset(state: RumorV3State) -> str:
        workflow = state.get("rumor_workflow") or {}
        if not workflow.get("is_verification"):
            return "conversation"
        if workflow.get("source_url") and services.web_fetch_enabled:
            return "fetch_original"
        if workflow.get("source_url") and not workflow.get("initial_claim"):
            return "needs_input"
        return "extract_claim"

    async def conversation(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = _set_stage(state, "conversation")
        return {"rumor_workflow": workflow, "messages": [AIMessage(content=await services.chat(str(workflow.get("raw_input", "")), config))]}

    async def fetch_original(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = dict(state.get("rumor_workflow") or {})
        degradations = list(workflow.get("degradation_codes") or [])
        try:
            page = await services.fetch_original(str(workflow.get("source_url", "")), config)
        except Exception:
            page = None
            degradations.append("original_fetch_unavailable")
        return {"rumor_workflow": _set_stage(state, "fetch_original", original_page=page, degradation_codes=list(dict.fromkeys(degradations)))}

    def route_after_fetch(state: RumorV3State) -> str:
        workflow = state.get("rumor_workflow") or {}
        if not workflow.get("original_page") and not workflow.get("initial_claim"):
            return "needs_input"
        return "extract_claim"

    async def needs_input(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        checkability = {
            "claim": "",
            "claim_type": "unclear",
            "checkability": "needs_clarification",
            "reason": "网页抓取失败或未启用，且用户没有提供独立的文字主张。",
        }
        workflow = _set_stage(state, "needs_input", checkability=checkability, claim_context=None, evidence=[], decision=_safe_boundary_decision(checkability))
        report = _report_from_state({**state, "rumor_workflow": workflow})
        return {"rumor_workflow": workflow, "rumor_report": report, "messages": [AIMessage(content=_render_report(report))]}

    async def extract_claim(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        context = await services.extract_claim(str(workflow.get("raw_input", "")), workflow.get("original_page"), workflow.get("source_url"), config)
        try:
            parsed = ClaimContext.model_validate(context)
        except Exception:
            parsed = ClaimContext.model_validate(_fallback_claim_context(str(workflow.get("raw_input", "")), workflow.get("original_page"), workflow.get("source_url")))
        if len(parsed.subclaims) > 3:
            parsed = parsed.model_copy(update={"subclaims": parsed.subclaims[:3]})
        sanitized = sanitize_text_risk_analysis(parsed, str(workflow.get("raw_input", "")))
        parsed = sanitized if isinstance(sanitized, ClaimContext) else ClaimContext.model_validate(sanitized)
        parsed = repair_temporality(parsed)
        research_plan = build_research_plan(parsed)
        return {
            "rumor_workflow": _set_stage(
                state,
                "extract_claim",
                claim_context=parsed.model_dump(mode="json"),
                normalized_claim=parsed.normalized_claim,
                research_plan=research_plan,
            )
        }

    async def checkability(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        context = ClaimContext.model_validate(workflow.get("claim_context") or {})
        assessment = assess_checkability(context.normalized_claim)
        payload = assessment.model_copy(update={"claim_context": context}).model_dump(mode="json")
        return {"rumor_workflow": _set_stage(state, "checkability", checkability=payload)}

    def route_checkability(state: RumorV3State) -> str:
        value = ((state.get("rumor_workflow") or {}).get("checkability") or {}).get("checkability")
        return "dispatch" if value == Checkability.CHECKABLE_NOW.value else "boundary_report"

    async def boundary_report(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        decision = _safe_boundary_decision(workflow.get("checkability"))
        workflow = _set_stage(state, "report", evidence=[], evidence_review=None, decision=decision, timeline=None)
        report = _report_from_state({**state, "rumor_workflow": workflow})
        return {"rumor_workflow": workflow, "rumor_report": report, "messages": [AIMessage(content=_render_report(report))]}

    async def dispatch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        authority_query = str(((workflow.get("research_plan") or {}).get("queries") or {}).get("authority") or "")
        status = {
            "rag": {"status": "pending"},
            "web": {"status": "pending" if services.web_search_enabled else "skipped"},
            "classifier": {"status": "pending" if services.classifier_enabled or services.classifier_required else "skipped"},
            "authority": {"status": "pending" if services.web_search_enabled and authority_query else "skipped"},
        }
        return {"rumor_workflow": _set_stage(state, "parallel_collection"), "rumor_branch_status": status}

    async def rag_branch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        started_at, started_clock = _iso_now(), time.monotonic()
        claim_context = (state.get("rumor_workflow") or {}).get("claim_context") or {}
        try:
            payload = await services.retrieve_rag(claim_context, config)
            status = _branch_update("completed", started_at, started_clock, result_count=len(payload.get("matches", [])))
        except Exception:
            payload = KnowledgeRetrievalResult(
                status="unavailable",
                query=str(claim_context.get("normalized_claim") or ""),
                matches=[],
                threshold=0.0,
                authoritative=False,
                note="本地知识库本轮不可用；该分支不会影响证据规则裁决。",
                degradation_codes=["rag_unavailable"],
            ).model_dump(mode="json")
            status = _branch_update("unavailable", started_at, started_clock, error_code="rag_unavailable")
        return {"v3_rag_result": payload, "rumor_branch_status": {"rag": status}}

    async def web_branch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        if not services.web_search_enabled or not services.web_fetch_enabled:
            return {"v3_web_research": None, "rumor_branch_status": {"web": {"status": "skipped", "result_count": 0}}}
        started_at, started_clock = _iso_now(), time.monotonic()
        try:
            workflow = state.get("rumor_workflow") or {}
            research_context = {
                **dict(workflow.get("claim_context") or {}),
                "research_plan": workflow.get("research_plan") or {},
            }
            payload = await services.research_web(research_context, config)
            status = _branch_update("completed", started_at, started_clock, result_count=len(payload.get("evidence", [])))
        except Exception:
            payload = {"status": "unavailable", "evidence": [], "observed_urls": [], "rejected_evidence": []}
            status = _branch_update("unavailable", started_at, started_clock, error_code="web_research_unavailable")
        return {"v3_web_research": payload, "rumor_branch_status": {"web": status}}

    async def classifier_branch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        if not services.classifier_enabled:
            return {
                "v3_classifier_signal": {
                    "status": "unavailable",
                    "role": "auxiliary_signal",
                    "label": "uncertain",
                    "aggregate_label": "uncertain",
                    "rationale": "分类器未配置",
                    "authoritative": False,
                    "model_id": os.getenv("RUMOR_MODEL_NAME", ""),
                    "api_style": os.getenv("RUMOR_MODEL_API_STYLE", "modelscope_chat"),
                    "subclaims": [],
                },
                "rumor_branch_status": {
                    "classifier": {
                        "status": "unavailable" if services.classifier_required else "skipped",
                        "result_count": 0,
                        "error_code": "classifier_not_configured" if services.classifier_required else None,
                    }
                },
            }
        started_at, started_clock = _iso_now(), time.monotonic()
        try:
            payload = await services.classify((state.get("rumor_workflow") or {}).get("claim_context") or {}, config)
            subclaims = payload.get("subclaims", [])
            branch_state = "completed" if payload.get("status") in {"ok", "partial"} else "unavailable"
            status = _branch_update(
                branch_state,
                started_at,
                started_clock,
                result_count=sum(1 for item in subclaims if item.get("status") == "ok"),
                error_code=None if branch_state == "completed" else "classifier_unavailable",
            )
        except Exception:
            payload = {"status": "unavailable", "role": "auxiliary_signal", "label": "uncertain", "rationale": "分类器调用失败", "authoritative": False}
            status = _branch_update("unavailable", started_at, started_clock, error_code="classifier_unavailable")
        return {"v3_classifier_signal": payload, "rumor_branch_status": {"classifier": status}}

    async def authority_branch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        context = workflow.get("claim_context") or {}
        plan = workflow.get("research_plan") or {}
        authority_query = str((plan.get("queries") or {}).get("authority") or "")
        if not services.web_search_enabled or not authority_query:
            return {"v3_authority_research": None, "rumor_branch_status": {"authority": {"status": "skipped", "result_count": 0}}}
        started_at, started_clock = _iso_now(), time.monotonic()
        try:
            payload = await services.research_authority({**dict(context), "research_plan": plan}, config)
            status = _branch_update("completed", started_at, started_clock, result_count=len(payload.get("evidence", [])))
        except Exception:
            payload = {"status": "unavailable", "evidence": [], "observed_urls": [], "rejected_evidence": []}
            status = _branch_update("unavailable", started_at, started_clock, error_code="authority_research_unavailable")
        return {"v3_authority_research": payload, "rumor_branch_status": {"authority": status}}

    async def timeline_research_branch(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        if not services.timeline_enabled or not services.web_search_enabled or not services.web_fetch_enabled:
            return {
                "v3_timeline_research": None,
                "rumor_branch_status": {},
            }
        started_at, started_clock = _iso_now(), time.monotonic()
        try:
            payload = await services.research_timeline(
                (state.get("rumor_workflow") or {}).get("claim_context") or {},
                config,
            )
            status = _branch_update(
                "completed",
                started_at,
                started_clock,
                result_count=len(payload.get("evidence", [])),
            )
        except Exception:
            payload = {
                "status": "unavailable",
                "evidence": [],
                "observed_urls": [],
                "rejected_evidence": [],
            }
            status = _branch_update(
                "unavailable",
                started_at,
                started_clock,
                error_code="timeline_research_unavailable",
            )
        return {
            "v3_timeline_research": payload,
            "rumor_branch_status": {"timeline_research": status},
        }

    async def normalize_evidence(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        branches = {
            "web": state.get("v3_web_research"),
            "authority": state.get("v3_authority_research"),
            "timeline": state.get("v3_timeline_research"),
            "supplement": state.get("v3_supplement_research"),
        }
        evidence, rejected = merge_research_branches(branches)
        context = ClaimContext.model_validate((state.get("rumor_workflow") or {}).get("claim_context") or {})
        observed_urls = {
            normalize_url(str(url))
            for name in ("web", "authority", "supplement")
            for url in ((branches.get(name) or {}).get("observed_urls") or [])
            if isinstance(url, str)
        }
        capabilities = (state.get("rumor_workflow") or {}).get("capabilities") or {}
        if capabilities.get("web_fetch", True):
            try:
                await rescue_unverified_evidence(evidence, context, observed_urls)
            except Exception as exc:
                _rescue_logger.warning("deterministic rescue step failed: %s", exc)
            try:
                existing_urls = {
                    normalize_url(str(item.get("url") or ""))
                    for item in evidence
                    if isinstance(item, dict) and item.get("url")
                }
                swept = await sweep_observed_candidates(context, list(observed_urls), existing_urls)
                if swept:
                    evidence.extend(swept)
            except Exception as exc:
                _rescue_logger.warning("deterministic sweep step failed: %s", exc)
        parsed_evidence: list[EvidenceItem] = []
        for index, item in enumerate(evidence):
            try:
                parsed_evidence.append(EvidenceItem.model_validate(item))
            except Exception as exc:
                rejected.append(
                    {
                        "evidence_id": item.get("id", f"invalid-{index + 1}"),
                        "reason_code": "invalid_schema",
                        "explanation": f"证据字段非法：{exc}",
                    }
                )
        normalized, time_errors = normalize_evidence_items(parsed_evidence, context)
        for evidence_id, code in time_errors.items():
            rejected.append({"evidence_id": evidence_id, "reason_code": code, "explanation": "证据时间字段未通过代码校验"})
        normalized_json = [item.model_dump(mode="json") for item in normalized]
        degradations = list((state.get("rumor_workflow") or {}).get("degradation_codes") or [])
        rag_payload = state.get("v3_rag_result") or {}
        if isinstance(rag_payload, Mapping):
            degradations.extend(str(code) for code in rag_payload.get("degradation_codes", []) if code)
        for name, item in (state.get("rumor_branch_status") or {}).items():
            if item.get("status") == "unavailable" and item.get("error_code"):
                degradations.append(str(item["error_code"]))
        workflow = _set_stage(
            state,
            "evidence_normalization",
            rag_result=state.get("v3_rag_result"),
            classifier_signal=state.get("v3_classifier_signal"),
            evidence=normalized_json,
            research_rejected=rejected,
            degradation_codes=list(dict.fromkeys(degradations)),
            branch_status=dict(state.get("rumor_branch_status") or {}),
        )
        return {"rumor_workflow": workflow, "v3_rejected_evidence": rejected}

    async def critic(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        count = int(state.get("v3_supplement_count") or 0)
        base = build_evidence_review(workflow.get("claim_context") or {}, list(workflow.get("evidence") or []), supplement_count=count)
        try:
            suggested = await services.review_evidence(workflow.get("claim_context") or {}, list(workflow.get("evidence") or []), config)
            parsed = EvidenceReview.model_validate(suggested)
            base["notes"] = parsed.notes or base["notes"]
            if base["supplement_needed"] and parsed.supplement_query:
                base["supplement_query"] = (f"{base['supplement_query']}；审查建议：{parsed.supplement_query}")[:500]
        except Exception:
            pass
        if base["supplement_needed"]:
            priority_urls: list[str] = []
            rag_result = workflow.get("rag_result") or {}
            for match in rag_result.get("matches", []) if isinstance(rag_result, Mapping) else []:
                if not isinstance(match, Mapping):
                    continue
                for url in match.get("authoritative_sources", []) or []:
                    if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in priority_urls:
                        priority_urls.append(url)
                    if len(priority_urls) >= 2:
                        break
                if len(priority_urls) >= 2:
                    break
            if priority_urls:
                base["supplement_query"] = (f"{base['supplement_query']}；优先抓取并核对知识库提示的权威候选：{' '.join(priority_urls)}")[:500]
        if not services.web_search_enabled:
            base["supplement_needed"] = False
            base["supplement_query"] = ""
        # V3 uses exactly two bounded searches: discovery and authority.  The
        # critic reports the remaining gap but cannot trigger a third query.
        base["supplement_needed"] = False
        base["supplement_query"] = ""
        if base["threshold_gap"]:
            base["notes"] += " 已达到两阶段搜索预算，本轮不再发起模型自由补检。"
        return {"v3_evidence_review": base, "rumor_workflow": _set_stage(state, "evidence_review", evidence_review=base)}

    def route_after_critic(state: RumorV3State) -> str:
        review = state.get("v3_evidence_review") or {}
        return "supplement" if review.get("supplement_needed") and int(state.get("v3_supplement_count") or 0) < 1 else "adjudicate"

    async def supplement(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        started_at, started_clock = _iso_now(), time.monotonic()
        workflow = state.get("rumor_workflow") or {}
        try:
            payload = await services.research_web(workflow.get("claim_context") or {}, config, supplementary=True, gap_query=str((state.get("v3_evidence_review") or {}).get("supplement_query", "")))
            status = _branch_update("completed", started_at, started_clock, result_count=len(payload.get("evidence", [])))
        except Exception:
            payload = {"status": "unavailable", "evidence": [], "observed_urls": [], "rejected_evidence": []}
            status = _branch_update("unavailable", started_at, started_clock, error_code="supplement_research_unavailable")
        return {
            "v3_supplement_research": payload,
            "v3_supplement_count": 1,
            "rumor_branch_status": {"supplement": status},
            "rumor_workflow": _set_stage(state, "supplementary_research", supplement_count=1),
        }

    async def adjudicate(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        observed_urls: set[str] = set()
        for payload in (state.get("v3_web_research"), state.get("v3_authority_research"), state.get("v3_supplement_research")):
            if isinstance(payload, Mapping):
                observed_urls.update(str(url) for url in payload.get("observed_urls", []))
        decision = decide_evidence(
            evidence=list(workflow.get("evidence") or []),
            classifier_signal=workflow.get("classifier_signal"),
            allowed_urls=observed_urls,
            original_url=workflow.get("source_url"),
            claim_context=workflow.get("claim_context"),
        ).model_dump(mode="json")
        existing_excluded = list(decision.get("excluded_evidence") or [])
        existing_keys = {(item.get("evidence_id"), item.get("reason_code")) for item in existing_excluded}
        for item in state.get("v3_rejected_evidence") or []:
            key = (item.get("evidence_id", "unknown"), item.get("reason_code", "invalid_research_evidence"))
            if key in existing_keys:
                continue
            existing_excluded.append(
                {
                    "evidence_id": key[0],
                    "reason_code": key[1],
                    "explanation": item.get("explanation", "研究证据未通过结构或来源校验"),
                }
            )
            existing_keys.add(key)
        decision["excluded_evidence"] = existing_excluded
        decision["decision_status"] = derive_decision_status(
            str(decision.get("verdict") or "证据不足"),
            list(workflow.get("evidence") or []),
            existing_excluded,
        )
        return {"rumor_workflow": _set_stage(state, "adjudicate", decision=decision)}

    async def timeline(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = state.get("rumor_workflow") or {}
        if not services.timeline_enabled:
            result = {
                "timeline_status": "insufficient",
                "events": [],
                "note": "传播溯源实验默认关闭；本版本只展示本轮证据的发布时间序列，不推断首发或传播关系。",
                "candidate_count": 0,
                "dated_count": 0,
                "traceable_count": 0,
            }
            return {"rumor_workflow": _set_stage(state, "timeline", timeline=result)}
        timeline_status = ((state.get("rumor_branch_status") or {}).get("timeline_research") or {}).get("status")
        result = build_timeline(
            evidence=list(workflow.get("evidence") or []),
            decision=workflow.get("decision") or {},
            rag_result=workflow.get("rag_result"),
            timeline_research_status=str(timeline_status) if timeline_status else None,
        ).model_dump(mode="json")
        return {"rumor_workflow": _set_stage(state, "timeline", timeline=result)}

    async def explain(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = _set_stage(state, "explain")
        explanation = await services.explain(workflow, config)
        return {"rumor_workflow": workflow, "v3_explanation": explanation}

    async def finalize(state: RumorV3State, config: RunnableConfig) -> dict[str, Any]:
        workflow = _set_stage(state, "report", branch_status=dict(state.get("rumor_branch_status") or {}))
        report = _report_from_state({**state, "rumor_workflow": workflow})
        return {"rumor_workflow": workflow, "rumor_report": report, "messages": [AIMessage(content=_render_report(report))]}

    builder = StateGraph(RumorV3State)
    builder.add_node("reset_turn", reset_turn)
    builder.add_node("conversation", conversation)
    builder.add_node("fetch_original", fetch_original)
    builder.add_node("needs_input", needs_input)
    builder.add_node("extract_claim", extract_claim)
    builder.add_node("checkability", checkability)
    builder.add_node("boundary_report", boundary_report)
    builder.add_node("dispatch", dispatch)
    builder.add_node("rag", rag_branch)
    builder.add_node("web", web_branch)
    builder.add_node("classifier", classifier_branch)
    builder.add_node("authority", authority_branch)
    builder.add_node("timeline_research", timeline_research_branch)
    builder.add_node("normalize", normalize_evidence)
    builder.add_node("critic", critic)
    builder.add_node("adjudicate", adjudicate)
    builder.add_node("timeline", timeline)
    builder.add_node("explain", explain)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "reset_turn")
    builder.add_conditional_edges("reset_turn", route_after_reset, {"conversation": "conversation", "fetch_original": "fetch_original", "needs_input": "needs_input", "extract_claim": "extract_claim"})
    builder.add_edge("conversation", END)
    builder.add_conditional_edges("fetch_original", route_after_fetch, {"needs_input": "needs_input", "extract_claim": "extract_claim"})
    builder.add_edge("needs_input", END)
    builder.add_edge("extract_claim", "checkability")
    builder.add_conditional_edges("checkability", route_checkability, {"dispatch": "dispatch", "boundary_report": "boundary_report"})
    builder.add_edge("boundary_report", END)
    builder.add_conditional_edges("dispatch", make_parallel_sends)
    for branch in ("rag", "web", "classifier", "authority", "timeline_research"):
        builder.add_edge(branch, "normalize")
    builder.add_edge("normalize", "critic")
    builder.add_edge("critic", "adjudicate")
    builder.add_edge("adjudicate", "timeline")
    builder.add_edge("timeline", "explain")
    builder.add_edge("explain", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def make_default_v3_services() -> RumorV3Services:
    import os

    from deerflow.config.app_config import get_app_config

    configured = {tool.name for tool in get_app_config().tools}
    required = os.getenv("RUMOR_CLASSIFIER_REQUIRED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    timeline_enabled = os.getenv("RUMOR_TIMELINE_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return RumorV3Services(
        web_search_enabled="web_search" in configured,
        web_fetch_enabled="web_fetch" in configured,
        classifier_enabled=bool(os.getenv("RUMOR_MODEL_BASE_URL", "").strip()),
        classifier_required=required,
        timeline_enabled=timeline_enabled,
    )


__all__ = [
    "RumorV3Services",
    "build_evidence_review",
    "build_rumor_graph_v3",
    "detect_claim_domain",
    "make_default_v3_services",
    "make_parallel_sends",
    "merge_research_branches",
    "sanitize_text_risk_analysis",
]
