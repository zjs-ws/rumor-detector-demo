"""Deterministic helpers for collecting traceable propagation records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .source_policy import registrable_group

_SPACE_RE = re.compile(r"\s+")
_DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?"),
    re.compile(r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)"),
)
_TOPIC_NOISE = {
    "不能",
    "可以",
    "可能",
    "是否",
    "属实",
    "谣言",
    "真的",
    "网传",
    "说法",
    "一律",
    "造成",
    "进行",
    "相关",
}
_TOPIC_CONCEPT_GROUPS = (
    ("管道疏通剂", "疏通剂"),
    ("洁厕灵", "洁厕剂"),
    ("强碱", "氢氧化钠", "苛性钠"),
    ("强酸", "盐酸", "草酸"),
    ("热水", "高温", "升温"),
    ("爆射", "喷溅", "飞溅", "喷涌"),
    ("毁容", "灼伤", "烧伤", "腐蚀伤害"),
)


def build_timeline_query(claim_context: Mapping[str, object]) -> str:
    claim = str(claim_context.get("normalized_claim") or "").strip()
    return f"{claim} 最早 网传 辟谣 传播"[:500]


def parse_search_results(raw: object, *, limit: int = 5) -> list[dict[str, str]]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw) if isinstance(raw, Mapping) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []

    normalized: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in results:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or item.get("href") or item.get("link") or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or url in seen_urls:
            continue
        seen_urls.add(url)
        normalized.append(
            {
                "title": _clean_text(item.get("title")),
                "url": url,
                "content": _clean_text(item.get("content") or item.get("body") or item.get("snippet")),
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def parse_fetch_result(raw: object) -> dict[str, object] | None:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw) if isinstance(raw, Mapping) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not str(payload.get("content") or "").strip() or not str(payload.get("fetched_at") or "").strip():
        return None
    return payload


def extract_timeline_date(*values: object) -> str | None:
    today = datetime.now(UTC).date()
    for value in values:
        text = str(value or "")
        for pattern in _DATE_PATTERNS:
            for match in pattern.finditer(text[:4000]):
                try:
                    parsed = datetime(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    ).date()
                except ValueError:
                    continue
                if parsed <= today:
                    return parsed.isoformat()
    return None


def infer_timeline_event_type(*values: object) -> str:
    text = " ".join(str(value or "").lower() for value in values)
    if any(token in text for token in ("再次", "再度", "又传", "翻炒", "resurface")):
        return "resurgence"
    if any(token in text for token in ("变体", "改称", "演变", "mutation")):
        return "mutation"
    if any(token in text for token in ("疯传", "热传", "刷屏", "viral", "amplif")):
        return "amplification"
    if any(token in text for token in ("辟谣", "澄清", "不实", "假的", "谣言", "myth", "debunk", "false")):
        return "correction"
    if any(token in text for token in ("核查", "核实", "fact check", "fact-check", "verify")):
        return "verification"
    return "spread"


def timeline_candidate_relevant(claim: str, *values: object) -> bool:
    """Require multiple topic concepts, not one repeated entity name."""
    normalized_claim = re.sub(r"[^\w\u4e00-\u9fff]+", "", claim.lower())
    candidate = re.sub(r"[^\w\u4e00-\u9fff]+", "", " ".join(str(value or "") for value in values).lower())
    if not normalized_claim or not candidate:
        return False
    active_groups = [group for group in _TOPIC_CONCEPT_GROUPS if any(term in normalized_claim for term in group)]
    if len(active_groups) >= 2:
        covered = sum(any(term in candidate for term in group) for group in active_groups)
        return covered >= 2
    grams = {
        normalized_claim[index : index + 2]
        for index in range(max(0, len(normalized_claim) - 1))
        if normalized_claim[index : index + 2] not in _TOPIC_NOISE
    }
    return sum(1 for gram in grams if gram in candidate) >= 3


def build_timeline_evidence(
    *,
    index: int,
    search_result: Mapping[str, object],
    fetch_result: Mapping[str, object],
    claim_ids: list[str],
) -> dict[str, object]:
    url = str(fetch_result.get("source_url") or search_result.get("url") or "").strip()
    title = _clean_text(fetch_result.get("title") or search_result.get("title") or url)
    content = _clean_text(fetch_result.get("content"))
    snippet = _clean_text(search_result.get("content"))
    published_at = extract_timeline_date(
        fetch_result.get("published_at"),
        content[:1500],
        snippet,
        title,
        url,
    )
    event_type = infer_timeline_event_type(title, snippet, content[:800])
    change_summary = {
        "correction": "该页面对相关说法进行了核查、澄清或纠正。",
        "verification": "该页面记录了对相关说法的事实核查。",
        "mutation": "该页面标题或摘要显示说法出现了新的表述版本。",
        "amplification": "该页面记录了相关说法被集中扩散。",
        "resurgence": "该页面记录了相关说法再次出现或被重新传播。",
    }.get(event_type, "")
    return {
        "id": f"timeline-{index}",
        "title": title or url,
        "url": url,
        "publisher": urlsplit(url).hostname or "未知",
        "published_at": published_at,
        "stance": "context",
        "source_level": "C",
        "claimed_source_level": "C",
        "directness": "direct",
        "authority_scope": False,
        "authority_reason": "传播记录不参与真假裁决",
        "independent_group": registrable_group(url),
        "temporal_relevance": "event_match" if published_at else "unknown",
        "current_validity_confirmed": False,
        "fetched_at": str(fetch_result.get("fetched_at") or "") or None,
        "extraction_status": "ok",
        "claim_ids": claim_ids,
        "claim_variant": title or snippet[:240],
        "change_summary": change_summary,
        "timeline_only": True,
        "timeline_event_type": event_type,
        "summary": (content or snippet)[:600],
        "provenance": "web",
    }


def _clean_text(value: object) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


__all__ = [
    "build_timeline_evidence",
    "build_timeline_query",
    "extract_timeline_date",
    "infer_timeline_event_type",
    "parse_fetch_result",
    "parse_search_results",
    "timeline_candidate_relevant",
]
