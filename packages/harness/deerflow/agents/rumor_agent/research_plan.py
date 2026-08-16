"""Deterministic claim-time repair and authority-query planning.

The language model may suggest wording, but it cannot choose trusted domains or
turn a domain keyword such as ``药物`` into a current-status claim.  This module
keeps those decisions auditable and reusable by the graph and tests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .schemas import ClaimContext, ClaimTemporality
from .source_policy import source_registry

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_FUTURE_RE = re.compile(r"(?:未来|将来|明年|明日|即将|预计|预测|会不会|将会)")
_CURRENT_RE = re.compile(r"(?:目前|现在|现行|最新|当前|截至(?:今日|今天|目前|\d{4}年))")
_HISTORICAL_RE = re.compile(
    r"(?:曾经?|历史上|当年|过去|此前|已经结束|于\s*(?:18|19|20)\d{2}年|"
    r"(?:18|19|20)\d{2}\s*[-—至到]\s*(?:18|19|20)\d{2}|"
    r"塔斯基吉|tuskegee|mk[-_ ]?ultra)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)")
_SAFE_QUERY_RE = re.compile(r"[^\w\u4e00-\u9fff\-\s:/.'\"()]+")
_DOMAIN_DEFAULT_TARGETS: dict[str, tuple[str, ...]] = {
    "medical": ("who.int", "cdc.gov", "nhc.gov.cn"),
    "legal": ("npc.gov.cn", "court.gov.cn", "spp.gov.cn"),
    "finance": ("pbc.gov.cn", "csrc.gov.cn", "stats.gov.cn"),
    "science": ("science.org", "nature.com"),
    "technology": ("nist.gov", "cac.gov.cn"),
}


def repair_temporality(context: ClaimContext) -> ClaimContext:
    """Apply deterministic temporal precedence without trusting domain words."""

    claim = " ".join(
        [context.normalized_claim]
        + [item.text for item in context.subclaims if item.material]
    )
    if _FUTURE_RE.search(claim):
        # Future checkability is handled by the boundary classifier.  Keeping
        # UNKNOWN prevents current-status evidence rules from firing early.
        temporality = ClaimTemporality.UNKNOWN
        basis = "future_marker"
    elif _CURRENT_RE.search(claim):
        temporality = ClaimTemporality.CURRENT_STATUS
        basis = "current_marker"
    elif _HISTORICAL_RE.search(claim) or _YEAR_RE.search(claim):
        temporality = ClaimTemporality.EVENT_BOUND
        basis = "historical_marker"
    elif context.temporality != ClaimTemporality.UNKNOWN:
        temporality = context.temporality
        basis = context.temporality_basis if context.temporality_basis not in {"", "unknown"} else "model"
    else:
        temporality = ClaimTemporality.UNKNOWN
        basis = "unknown"
    return context.model_copy(
        update={"temporality": temporality, "temporality_basis": basis}
    )


def _safe_term(value: object, *, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    value = _URL_RE.sub("", value)
    value = _SAFE_QUERY_RE.sub(" ", value)
    return " ".join(value.split())[:limit]


def _matches_claim(claim: str, aliases: list[str]) -> bool:
    lowered = claim.casefold()
    return any(alias and alias.casefold() in lowered for alias in aliases)


def build_research_plan(context: ClaimContext | Mapping[str, Any]) -> dict[str, Any]:
    """Build one discovery query and one domain-locked authority query."""

    parsed = context if isinstance(context, ClaimContext) else ClaimContext.model_validate(context)
    parsed = repair_temporality(parsed)
    registry = source_registry()
    claim = _safe_term(parsed.normalized_claim, limit=280)
    claim_for_matching = " ".join(
        [parsed.normalized_claim]
        + [item.text for item in parsed.subclaims if item.material]
    )
    entities: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    aliases_for_query: list[str] = []

    for entry in registry.get("authority_entities", []):
        aliases = [_safe_term(item, limit=80) for item in entry.get("aliases", [])]
        aliases = [item for item in aliases if item]
        if not _matches_claim(claim_for_matching, aliases):
            continue
        canonical = _safe_term(entry.get("canonical_name"), limit=100)
        domains = [str(item).lower().strip() for item in entry.get("domains", []) if str(item).strip()]
        entities.append(
            {
                "canonical_name": canonical,
                "aliases": aliases,
                "evidence_terms": [
                    item
                    for item in (
                        _safe_term(value, limit=80)
                        for value in entry.get("evidence_terms", [])
                    )
                    if item
                ],
                "role": _safe_term(entry.get("role"), limit=120),
            }
        )
        targets.append(
            {
                "organization": canonical,
                "domains": domains,
                "scope": _safe_term(entry.get("scope"), limit=160),
            }
        )
        evidence_terms = entities[-1]["evidence_terms"]
        aliases_for_query.extend(aliases[:2])
        aliases_for_query.extend(evidence_terms[:2])

    if not targets:
        lowered_claim = claim_for_matching.casefold()
        for entry in registry.get("official_sources", []):
            keywords = [str(item).casefold() for item in entry.get("scope_keywords", [])]
            if not any(keyword and keyword in lowered_claim for keyword in keywords):
                continue
            domains = [str(item).lower().strip() for item in entry.get("domains", []) if str(item).strip()]
            if not domains:
                continue
            targets.append(
                {
                    "organization": domains[0],
                    "domains": domains,
                    "scope": "由受控职权关键词匹配",
                }
            )
            if len(targets) >= 2:
                break

    if not targets and parsed.domain.value in _DOMAIN_DEFAULT_TARGETS:
        domains = list(_DOMAIN_DEFAULT_TARGETS[parsed.domain.value])
        targets.append(
            {
                "organization": f"{parsed.domain.value}-authority-route",
                "domains": domains,
                "scope": "专业领域默认受控来源；具体等级仍由来源策略校正",
            }
        )

    risk = parsed.text_risk_analysis
    safe_hints = [_safe_term(item, limit=100) for item in risk.search_hints[:3]]
    alias_terms = list(dict.fromkeys(item for item in aliases_for_query + safe_hints if item))[:4]
    discovery_parts = [claim, *alias_terms, "fact check debunk 辟谣 核查"]
    discovery_query = " ".join(part for part in discovery_parts if part)[:500]

    target_domains = list(
        dict.fromkeys(
            domain
            for target in targets
            for domain in target.get("domains", [])
            if domain
        )
    )[:3]
    site_clause = " OR ".join(f"site:{domain}" for domain in target_domains)
    authority_terms = alias_terms[:4]
    authority_query = ""
    if site_clause:
        authority_query = " ".join(
            part
            for part in (
                f"({site_clause})" if len(target_domains) > 1 else site_clause,
                *authority_terms,
                claim,
            )
            if part
        )[:500]

    return {
        "temporality": parsed.temporality.value,
        "temporality_basis": parsed.temporality_basis,
        "entities": entities,
        "authority_targets": targets,
        "queries": {
            "discovery": discovery_query,
            "authority": authority_query,
        },
    }


__all__ = ["build_research_plan", "repair_temporality"]
