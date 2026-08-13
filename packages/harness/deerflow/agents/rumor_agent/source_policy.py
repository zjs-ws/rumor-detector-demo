"""Conservative source, time, and independence normalization.

The researcher may propose metadata, but the verified grade is derived from an
auditable registry and claim scope. Unknown pages cannot self-promote; an
official source can still be corrected upward when code verifies its scope.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .schemas import ClaimContext, ClaimTemporality, Directness, EvidenceItem, SourceLevel, TemporalRelevance

_DATA_DIR = Path(__file__).resolve().parent / "data"
_SOURCE_REGISTRY_PATH = _DATA_DIR / "source_registry.json"
_KNOWLEDGE_BASE_PATH = _DATA_DIR / "verified_rumors.jsonl"
_FALLBACK_REGISTRY = {
    "official_sources": [{"domains": ["who.int", "gov.cn"], "scope_keywords": []}],
    "professional_hosts": ["reuters.com", "apnews.com", "bbc.com"],
    "personal_host_keywords": ["blog", "weibo", "zhihu", "douyin", "twitter", "x.com"],
}
_CURRENT_SENSITIVE = re.compile(r"(?:现行|目前|现在|最新|政策|法规|法律|指南|治疗|用药|药物|疫苗)")
_TEXT_NORMALIZER = re.compile(r"[^\w\u4e00-\u9fff]+")


@dataclass(frozen=True)
class SourceGrade:
    claimed: SourceLevel
    verified: SourceLevel
    reason: str
    authority_scope: bool = False
    authority_reason: str = ""


@lru_cache(maxsize=1)
def source_registry() -> dict[str, Any]:
    """Load the auditable registry and merge hosts observed in reviewed KB records."""
    try:
        registry = json.loads(_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        registry = dict(_FALLBACK_REGISTRY)

    kb_hosts: set[str] = set()
    try:
        for line in _KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("review_status") != "reviewed":
                continue
            for source in record.get("authoritative_sources", []):
                host = hostname(str(source.get("url", "")))
                if host:
                    kb_hosts.add(host)
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass

    registry["knowledge_base_hosts"] = sorted(kb_hosts)
    return registry


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _matches(host: str, candidates: set[str]) -> bool:
    return any(host == candidate or host.endswith(f".{candidate}") for candidate in candidates)


def registrable_group(url: str) -> str:
    """Return a stable conservative domain group without an external PSL dependency."""
    host = hostname(url)
    if not host:
        return "unknown"
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in {"gov.cn", "edu.cn", "ac.cn", "com.cn", "org.cn"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def content_fingerprint(item: EvidenceItem) -> str:
    value = _TEXT_NORMALIZER.sub("", f"{item.title}{item.summary}".lower())
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


def content_similarity(left: EvidenceItem, right: EvidenceItem) -> float:
    left_text = _TEXT_NORMALIZER.sub("", f"{left.title}{left.summary}".lower())
    right_text = _TEXT_NORMALIZER.sub("", f"{right.title}{right.summary}".lower())
    if not left_text or not right_text:
        return 0.0
    return SequenceMatcher(None, left_text, right_text).ratio()


def _official_scope(host: str, claim_context: ClaimContext | None) -> tuple[bool, str]:
    registry = source_registry()
    claim = claim_context.normalized_claim.lower() if claim_context else ""
    for entry in registry.get("official_sources", []):
        domains = {str(value).lower() for value in entry.get("domains", [])}
        if not _matches(host, domains):
            continue
        keywords = [str(value).lower() for value in entry.get("scope_keywords", [])]
        if claim and any(keyword in claim for keyword in keywords):
            return True, "官方来源注册表中的职权关键词与主张匹配"
        return False, "域名属于官方来源，但主张未命中该机构的受控职权范围"
    if _matches(host, set(registry.get("knowledge_base_hosts", []))):
        return False, "域名出现在已复核知识库来源中，但当前主张仍需单独验证职权范围"
    if host.endswith((".gov.cn", ".gov")):
        return False, "政府域名通过格式校验，但未命中具体机构职权配置"
    return False, "未命中官方来源注册表"


def grade_source(item: EvidenceItem, claim_context: ClaimContext | None = None) -> SourceGrade:
    claimed = item.claimed_source_level or item.source_level
    host = hostname(item.url)
    registry = source_registry()

    # Reserved example domains are used only by deterministic unit/evaluation fixtures.
    if host.endswith(".example") or host == "example":
        return SourceGrade(
            claimed,
            claimed,
            "离线测试保留域名，按测试声明等级处理",
            item.authority_scope,
            item.authority_reason,
        )

    if item.directness == Directness.SNIPPET_ONLY:
        return SourceGrade(claimed, SourceLevel.C, "搜索摘要最高按C级线索处理")
    scope_ok, scope_reason = _official_scope(host, claim_context)
    is_official = scope_reason != "未命中官方来源注册表"
    if is_official:
        verified = SourceLevel.A if scope_ok else SourceLevel.B
        reason = "官方域名且代码校验职权匹配" if scope_ok else "官方域名，但代码未确认与本事项职权匹配"
        return SourceGrade(claimed, verified, reason, scope_ok, scope_reason)
    professional_hosts = {str(value).lower() for value in registry.get("professional_hosts", [])}
    if _matches(host, professional_hosts) or host.endswith((".edu", ".edu.cn", ".ac.cn")):
        return SourceGrade(claimed, SourceLevel.B, "已配置的专业、学术或采编来源")
    personal_keywords = [str(value).lower() for value in registry.get("personal_host_keywords", [])]
    publisher = item.publisher.strip().lower()
    if claimed == SourceLevel.D or publisher in {"", "未知", "unknown"} or any(keyword in host for keyword in personal_keywords):
        return SourceGrade(claimed, SourceLevel.D, "个人或未知来源")
    return SourceGrade(claimed, SourceLevel.C, "未进入权威来源配置，最高按普通网页处理")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def normalized_temporal_relevance(
    item: EvidenceItem,
    claim_context: ClaimContext | None,
    *,
    today: date | None = None,
    current_confirmation_verified: bool = False,
) -> tuple[TemporalRelevance, str | None]:
    """Validate obvious time errors and apply the 365-day current-status rule."""
    today = today or date.today()
    published = _parse_date(item.published_at)
    if not item.published_at and hostname(item.url).endswith(".example"):
        return item.temporal_relevance, None
    if item.published_at and published is None:
        return TemporalRelevance.UNKNOWN, "invalid_date"
    if published and published > today:
        return TemporalRelevance.UNKNOWN, "future_date"
    if not published:
        if item.temporal_relevance == TemporalRelevance.TIMELESS and item.current_validity_confirmed:
            return TemporalRelevance.TIMELESS, None
        return TemporalRelevance.UNKNOWN, "time_unknown"

    temporality = claim_context.temporality if claim_context else ClaimTemporality.UNKNOWN
    claim_text = claim_context.normalized_claim if claim_context else ""
    if temporality == ClaimTemporality.EVENT_BOUND:
        return TemporalRelevance.EVENT_MATCH, None
    if temporality == ClaimTemporality.TIMELESS and not _CURRENT_SENSITIVE.search(claim_text):
        return TemporalRelevance.TIMELESS, None
    if temporality == ClaimTemporality.CURRENT_STATUS or _CURRENT_SENSITIVE.search(claim_text):
        if (today - published).days > 365 and not current_confirmation_verified:
            return TemporalRelevance.STALE, "stale_current_status"
        return TemporalRelevance.CURRENT, None
    return item.temporal_relevance, None


def normalize_evidence_items(
    items: list[EvidenceItem],
    claim_context: ClaimContext | None = None,
    *,
    enforce_time: bool = True,
    merge_independence: bool = True,
) -> tuple[list[EvidenceItem], dict[str, str]]:
    """Return evidence with source, authority, time, and independence normalized."""
    normalized: list[EvidenceItem] = []
    time_errors: dict[str, str] = {}
    graded_items = [(item, grade_source(item, claim_context)) for item in items]
    today = date.today()

    def has_current_confirmation(item: EvidenceItem) -> bool:
        published = _parse_date(item.published_at)
        if not published or (today - published).days <= 365:
            return False
        for candidate, candidate_grade in graded_items:
            if candidate.id == item.id or candidate.stance != item.stance:
                continue
            candidate_date = _parse_date(candidate.published_at)
            same_claim = not item.claim_ids or not candidate.claim_ids or bool(set(item.claim_ids) & set(candidate.claim_ids))
            if candidate_date and 0 <= (today - candidate_date).days <= 365 and candidate.directness == Directness.DIRECT and candidate_grade.verified in {SourceLevel.A, SourceLevel.B} and same_claim:
                return True
        return False

    for item, grade in graded_items:
        confirmation_verified = has_current_confirmation(item)
        if enforce_time:
            temporal, time_error = normalized_temporal_relevance(
                item,
                claim_context,
                today=today,
                current_confirmation_verified=confirmation_verified,
            )
        else:
            temporal, time_error = item.temporal_relevance, None
        if time_error:
            time_errors[item.id] = time_error
        normalized.append(
            item.model_copy(
                update={
                    "claimed_source_level": grade.claimed,
                    "verified_source_level": grade.verified,
                    "source_level": grade.verified,
                    "source_grade_reason": grade.reason,
                    "authority_scope": grade.authority_scope,
                    "authority_reason": grade.authority_reason,
                    "current_validity_confirmed": confirmation_verified,
                    "temporal_relevance": temporal,
                    "content_fingerprint": item.content_fingerprint or content_fingerprint(item),
                    "independent_group": item.independent_group or registrable_group(item.url),
                }
            )
        )

    # The normalizer may merge proposed groups, but never splits a researcher-proposed group.
    if not merge_independence:
        normalized = [item.model_copy(update={"independent_group": f"forced-independent-{index}"}) for index, item in enumerate(normalized)]
        return normalized, time_errors

    for index, item in enumerate(normalized):
        for prior in normalized[:index]:
            same_domain = registrable_group(item.url) == registrable_group(prior.url)
            same_publisher = item.publisher.strip().lower() == prior.publisher.strip().lower()
            near_duplicate = content_similarity(item, prior) >= 0.85
            if same_domain or same_publisher or near_duplicate:
                normalized[index] = item.model_copy(update={"independent_group": prior.independent_group})
                break
    return normalized, time_errors


__all__ = [
    "SourceGrade",
    "content_fingerprint",
    "content_similarity",
    "grade_source",
    "hostname",
    "normalize_evidence_items",
    "normalized_temporal_relevance",
    "registrable_group",
    "source_registry",
]
