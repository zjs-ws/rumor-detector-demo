"""Build a traceable, non-origin-claiming propagation timeline."""

from __future__ import annotations

from datetime import datetime

from .schemas import (
    EvidenceDecision,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceStance,
    KnowledgeRetrievalResult,
    TimelineEvent,
    TimelineEventType,
    TimelineResult,
    TimelineStatus,
)
from .source_policy import registrable_group


def _valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        return None


def _valid_fetch_timestamp(value: str | None) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _event_type(item: EvidenceItem) -> TimelineEventType:
    if item.provenance == EvidenceProvenance.ORIGINAL_PAGE:
        return TimelineEventType.SPREAD
    if item.change_summary:
        return TimelineEventType.MUTATION
    if item.stance == EvidenceStance.REFUTE:
        return TimelineEventType.CORRECTION
    if item.stance == EvidenceStance.SUPPORT:
        return TimelineEventType.VERIFICATION
    return TimelineEventType.SPREAD


def build_timeline(
    *,
    evidence: list[EvidenceItem | dict],
    decision: EvidenceDecision | dict,
    rag_result: KnowledgeRetrievalResult | dict | None = None,
) -> TimelineResult:
    """Create 3-8 dated traceable events or an explicit insufficient result."""
    parsed_decision = decision if isinstance(decision, EvidenceDecision) else EvidenceDecision.model_validate(decision)
    if parsed_decision.strength == "insufficient":
        return TimelineResult(note="规则裁决证据不足，因此不生成传播时间线。")

    items: list[EvidenceItem] = []
    for raw in evidence:
        try:
            item = raw if isinstance(raw, EvidenceItem) else EvidenceItem.model_validate(raw)
        except Exception:
            continue
        if item.directness.value == "snippet_only" or item.extraction_status != "ok":
            continue
        if item.provenance == EvidenceProvenance.WEB and not _valid_fetch_timestamp(item.fetched_at):
            continue
        if _valid_date(item.published_at):
            items.append(item)

    accepted = set(parsed_decision.accepted_evidence_ids)
    events: list[TimelineEvent] = []
    seen_groups: set[tuple[str, str]] = set()
    for item in sorted(items, key=lambda candidate: candidate.published_at or ""):
        event_date = _valid_date(item.published_at)
        if not event_date:
            continue
        group = (event_date, item.independent_group or registrable_group(item.url))
        if group in seen_groups:
            continue
        seen_groups.add(group)
        events.append(
            TimelineEvent(
                id=f"timeline-{len(events) + 1}",
                date=event_date,
                event_type=_event_type(item),
                claim_variant=item.claim_variant or item.summary,
                change_summary=item.change_summary,
                publisher=item.publisher,
                title=item.title,
                url=item.url,
                evidence_id=item.id,
                stance=item.stance,
                used_for_decision=item.id in accepted,
            )
        )

    if rag_result is not None:
        try:
            parsed_rag = rag_result if isinstance(rag_result, KnowledgeRetrievalResult) else KnowledgeRetrievalResult.model_validate(rag_result)
        except Exception:
            parsed_rag = None
        if parsed_rag:
            for match in parsed_rag.matches:
                event_date = _valid_date(match.event_date)
                if not event_date or not match.authoritative_sources:
                    continue
                url = match.authoritative_sources[0]
                group = (event_date, registrable_group(url))
                if group in seen_groups:
                    continue
                seen_groups.add(group)
                events.append(
                    TimelineEvent(
                        id=f"timeline-{len(events) + 1}",
                        date=event_date,
                        event_type=TimelineEventType.CORRECTION,
                        claim_variant=match.matched_variant,
                        change_summary="历史已核验记录，仅用于传播背景",
                        publisher=registrable_group(url),
                        title=match.canonical_claim,
                        url=url,
                        evidence_id=f"rag:{match.record_id}",
                        stance=EvidenceStance.CONTEXT,
                        used_for_decision=False,
                    )
                )

    events.sort(key=lambda event: event.date)
    events = events[:8]
    if len(events) < 3:
        return TimelineResult(note="少于三个带日期且可追溯的独立事件，不生成传播时间线。")

    first = events[0]
    events[0] = first.model_copy(update={"event_type": TimelineEventType.EARLIEST_FOUND})
    return TimelineResult(timeline_status=TimelineStatus.READY, events=events)


__all__ = ["build_timeline"]
