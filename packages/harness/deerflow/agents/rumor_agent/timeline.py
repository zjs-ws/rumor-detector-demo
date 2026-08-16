"""Build a traceable, non-origin-claiming propagation timeline."""

from __future__ import annotations

from datetime import datetime

from .rag import is_high_confidence_rag_match
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
    if item.timeline_event_type is not None:
        return item.timeline_event_type
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
    timeline_research_status: str | None = None,
) -> TimelineResult:
    """Create 3-8 dated traceable events or an explicit insufficient result."""
    parsed_decision = decision if isinstance(decision, EvidenceDecision) else EvidenceDecision.model_validate(decision)

    items: list[EvidenceItem] = []
    candidate_count = 0
    dated_count = 0
    dedicated_event_count = 0
    for raw in evidence:
        try:
            item = raw if isinstance(raw, EvidenceItem) else EvidenceItem.model_validate(raw)
        except Exception:
            continue
        candidate_count += 1
        if item.directness.value == "snippet_only" or item.extraction_status != "ok":
            continue
        if item.provenance == EvidenceProvenance.WEB and not _valid_fetch_timestamp(item.fetched_at):
            continue
        if _valid_date(item.published_at):
            dated_count += 1
            items.append(item)
            if item.timeline_only:
                dedicated_event_count += 1

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
                if not is_high_confidence_rag_match(match):
                    continue
                candidate_count += 1
                event_date = _valid_date(match.event_date)
                if not event_date or not match.authoritative_sources:
                    continue
                dated_count += 1
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
    events = [
        event.model_copy(update={"id": f"timeline-{index}"})
        for index, event in enumerate(events, start=1)
    ]
    traceable_count = len(events)
    if timeline_research_status in {"unavailable", "skipped"}:
        return TimelineResult(
            note=(
                "传播脉络专用检索未成功，本轮不使用普通取证或历史RAG拼接时间线。"
                f"已发现 {candidate_count} 条候选材料、{dated_count} 条有效日期记录。"
            ),
            candidate_count=candidate_count,
            dated_count=dated_count,
            traceable_count=traceable_count,
        )
    if timeline_research_status == "completed" and dedicated_event_count == 0:
        return TimelineResult(
            note=(
                "传播脉络专用检索没有形成可追溯节点，本轮不使用普通证据或历史RAG凑足时间线。"
                f"已发现 {candidate_count} 条候选材料、{dated_count} 条有效日期记录。"
            ),
            candidate_count=candidate_count,
            dated_count=dated_count,
            traceable_count=traceable_count,
        )
    if traceable_count < 3:
        return TimelineResult(
            note=(
                f"本轮发现 {candidate_count} 条候选材料，其中 {dated_count} 条具有可验证的有效发布日期，"
                f"去重后仅 {traceable_count} 个可追溯节点；少于三个，因此不生成传播时间线。"
            ),
            candidate_count=candidate_count,
            dated_count=dated_count,
            traceable_count=traceable_count,
        )

    first = events[0]
    events[0] = first.model_copy(update={"event_type": TimelineEventType.EARLIEST_FOUND})
    decision_note = "当前真假裁决仍为证据不足；时间线只描述公开页面的传播记录。" if parsed_decision.strength == "insufficient" else "真假结论仍由独立证据规则生成。"
    return TimelineResult(
        timeline_status=TimelineStatus.READY,
        events=events,
        note=f"最早节点仅表示本轮最早检索记录，不代表绝对首发。{decision_note}",
        candidate_count=candidate_count,
        dated_count=dated_count,
        traceable_count=traceable_count,
    )


__all__ = ["build_timeline"]
