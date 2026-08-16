"""Structured contracts for RumorBuster's evidence-first workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClaimType(StrEnum):
    PUBLIC_FACT = "public_fact"
    FUTURE_PREDICTION = "future_prediction"
    PRIVATE_FACT = "private_fact"
    OPINION = "opinion"
    SATIRE = "satire"
    UNCLEAR = "unclear"


class Checkability(StrEnum):
    CHECKABLE_NOW = "checkable_now"
    CHECKABLE_LATER = "checkable_later"
    NOT_PUBLICLY_CHECKABLE = "not_publicly_checkable"
    NOT_A_FACTUAL_CLAIM = "not_a_factual_claim"
    NEEDS_CLARIFICATION = "needs_clarification"


class EvidenceStance(StrEnum):
    SUPPORT = "support"
    REFUTE = "refute"
    CONTEXT = "context"


class SourceLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Directness(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    SNIPPET_ONLY = "snippet_only"


class TemporalRelevance(StrEnum):
    CURRENT = "current"
    EVENT_MATCH = "event_match"
    HISTORICAL_MATCH = "historical_match"
    TIMELESS = "timeless"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvidenceProvenance(StrEnum):
    ORIGINAL_PAGE = "original_page"
    WEB = "web"
    KNOWLEDGE_BASE = "knowledge_base"


class ClaimTemporality(StrEnum):
    CURRENT_STATUS = "current_status"
    EVENT_BOUND = "event_bound"
    TIMELESS = "timeless"
    UNKNOWN = "unknown"


class ClaimDomain(StrEnum):
    GENERAL = "general"
    MEDICAL = "medical"
    LEGAL = "legal"
    FINANCE = "finance"
    SCIENCE = "science"
    TECHNOLOGY = "technology"
    UNKNOWN = "unknown"


class TimelineStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT = "insufficient"


class TimelineEventType(StrEnum):
    EARLIEST_FOUND = "earliest_found"
    SPREAD = "spread"
    MUTATION = "mutation"
    AMPLIFICATION = "amplification"
    VERIFICATION = "verification"
    CORRECTION = "correction"
    RESURGENCE = "resurgence"


class Subclaim(BaseModel):
    id: str
    text: str
    material: bool = True


class TextRiskSignal(BaseModel):
    dimension: str
    level: str = "none"
    spans: list[str] = Field(default_factory=list)
    note: str = ""


class VerificationTarget(BaseModel):
    kind: str
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class TextRiskAnalysis(BaseModel):
    status: str = "unavailable"
    signals: list[TextRiskSignal] = Field(default_factory=list)
    verification_targets: list[VerificationTarget] = Field(default_factory=list)
    search_hints: list[str] = Field(default_factory=list)
    authoritative: bool = False


class ClaimContext(BaseModel):
    normalized_claim: str
    subclaims: list[Subclaim] = Field(default_factory=list)
    temporality: ClaimTemporality = ClaimTemporality.UNKNOWN
    temporality_basis: str = "unknown"
    event_date: str | None = None
    source_url: str | None = None
    domain: ClaimDomain = ClaimDomain.UNKNOWN
    domain_reason: str = ""
    text_risk_analysis: TextRiskAnalysis = Field(default_factory=TextRiskAnalysis)


class EvidenceReview(BaseModel):
    status: str = "completed"
    coverage_by_claim: dict[str, str] = Field(default_factory=dict)
    missing_claim_ids: list[str] = Field(default_factory=list)
    conflict_claim_ids: list[str] = Field(default_factory=list)
    duplicate_groups: list[str] = Field(default_factory=list)
    threshold_gap: bool = False
    preliminary_reason_codes: list[str] = Field(default_factory=list)
    supplement_needed: bool = False
    supplement_query: str = ""
    notes: str = ""


class SubclaimClassifierSignal(BaseModel):
    claim_id: str
    text: str
    status: str
    raw_label: str | None = None
    mapped_label: str = "uncertain"
    latency_ms: int | None = None
    input_hash: str = ""
    request_id: str = ""
    called_at: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None


class ClassifierSignal(BaseModel):
    status: str = "unavailable"
    role: str = "auxiliary_signal"
    label: str = "uncertain"
    rationale: str = ""
    authoritative: bool = False
    model_id: str = ""
    api_style: str = ""
    aggregate_label: str = "uncertain"
    subclaims: list[SubclaimClassifierSignal] = Field(default_factory=list)


class RagMatch(BaseModel):
    record_id: str
    canonical_claim: str
    similarity: float = Field(ge=0, le=1)
    matched_variant: str
    historical_verdict: str
    authoritative_sources: list[str] = Field(default_factory=list)
    event_date: str | None = None
    temporal_warning: str | None = None
    document_id: str = ""
    chunk_id: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    excerpt: str = ""
    publisher: str = ""
    source_url: str = ""
    published_at: str | None = None
    reviewed_at: str | None = None
    dense_similarity: float | None = Field(default=None, ge=0, le=1)
    sparse_similarity: float | None = Field(default=None, ge=0, le=1)
    fusion_score: float | None = Field(default=None, ge=0)
    retrieval_sources: list[str] = Field(default_factory=list)
    category: str = ""


class EvidenceItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    title: str
    url: str
    publisher: str = "未知"
    published_at: str | None = None
    stance: EvidenceStance
    source_level: SourceLevel = SourceLevel.D
    claimed_source_level: SourceLevel | None = None
    verified_source_level: SourceLevel | None = None
    source_grade_reason: str = ""
    directness: Directness = Directness.SNIPPET_ONLY
    authority_scope: bool = False
    authority_reason: str = ""
    independent_group: str = ""
    content_fingerprint: str = ""
    temporal_relevance: TemporalRelevance = TemporalRelevance.UNKNOWN
    current_validity_confirmed: bool = False
    fetched_at: str | None = None
    excerpt: str = ""
    document_hash: str = ""
    fetch_status: str = "unknown"
    fetch_attempts: list[dict[str, Any]] = Field(default_factory=list)
    content_type: str = ""
    final_url: str | None = None
    extraction_status: str = "ok"
    claim_ids: list[str] = Field(default_factory=list)
    claim_variant: str = ""
    change_summary: str = ""
    timeline_only: bool = False
    timeline_event_type: TimelineEventType | None = None
    summary: str
    provenance: EvidenceProvenance = EvidenceProvenance.WEB


class ExcludedEvidence(BaseModel):
    evidence_id: str
    reason_code: str
    explanation: str


class EvidenceDecision(BaseModel):
    verdict: str
    strength: str
    decision_status: str = "threshold_not_met"
    accepted_evidence_ids: list[str] = Field(default_factory=list)
    excluded_evidence: list[ExcludedEvidence] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    classifier_consistency: str = "unavailable"
    classifier_consistency_by_claim: dict[str, str] = Field(default_factory=dict)
    explanation: str
    subclaim_decisions: dict[str, str] = Field(default_factory=dict)


class KnowledgeRetrievalResult(BaseModel):
    status: str
    # Defaults keep legacy/degraded checkpoints readable. Successful retrieval
    # paths still populate both fields explicitly.
    query: str = ""
    matches: list[RagMatch] = Field(default_factory=list)
    threshold: float = 0.0
    authoritative: bool = False
    note: str = "历史记录仅用于召回相似主张，不能直接决定当前真假。"
    retrieval_mode: str = "sparse"
    embedding_model: str = ""
    index_version: str = ""
    document_count: int = 0
    chunk_count: int = 0
    queries: list[dict[str, Any]] = Field(default_factory=list)
    degradation_codes: list[str] = Field(default_factory=list)


class ClaimAssessment(BaseModel):
    claim: str
    claim_type: ClaimType
    checkability: Checkability
    reason: str
    claim_context: ClaimContext | None = None


class ResearchResult(BaseModel):
    status: str = "unavailable"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: str = ""


class TimelineEvent(BaseModel):
    id: str
    date: str
    date_precision: str = "day"
    event_type: TimelineEventType
    claim_variant: str
    change_summary: str = ""
    publisher: str
    title: str
    url: str
    evidence_id: str
    stance: EvidenceStance
    used_for_decision: bool = False


class TimelineResult(BaseModel):
    timeline_status: TimelineStatus = TimelineStatus.INSUFFICIENT
    events: list[TimelineEvent] = Field(default_factory=list)
    note: str = "时间线仅代表本轮公开可检索记录，不代表绝对传播源头。"
    candidate_count: int = 0
    dated_count: int = 0
    traceable_count: int = 0


__all__ = [
    "Checkability",
    "ClaimContext",
    "ClaimAssessment",
    "ClaimDomain",
    "ClaimTemporality",
    "ClaimType",
    "ClassifierSignal",
    "Directness",
    "EvidenceDecision",
    "EvidenceReview",
    "EvidenceItem",
    "EvidenceProvenance",
    "EvidenceStance",
    "KnowledgeRetrievalResult",
    "RagMatch",
    "ResearchResult",
    "SourceLevel",
    "Subclaim",
    "SubclaimClassifierSignal",
    "TemporalRelevance",
    "TextRiskAnalysis",
    "TextRiskSignal",
    "TimelineEvent",
    "TimelineEventType",
    "TimelineResult",
    "TimelineStatus",
    "VerificationTarget",
]
