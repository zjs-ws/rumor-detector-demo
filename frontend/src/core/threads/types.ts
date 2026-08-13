import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface RumorEvidenceItem {
  id: string;
  title: string;
  url: string;
  publisher: string;
  published_at?: string | null;
  stance: "support" | "refute" | "context";
  source_level: "A" | "B" | "C" | "D";
  claimed_source_level?: "A" | "B" | "C" | "D" | null;
  verified_source_level?: "A" | "B" | "C" | "D" | null;
  source_grade_reason?: string;
  directness: "direct" | "indirect" | "snippet_only";
  authority_scope?: boolean;
  authority_reason?: string;
  independent_group?: string;
  temporal_relevance: string;
  current_validity_confirmed?: boolean;
  fetched_at?: string | null;
  extraction_status?: string;
  content_fingerprint?: string;
  claim_ids?: string[];
  claim_variant?: string;
  change_summary?: string;
  provenance?: "original_page" | "web" | "knowledge_base";
  summary: string;
}

export interface RumorTimelineEvent {
  id: string;
  date: string;
  date_precision: string;
  event_type:
    | "earliest_found"
    | "spread"
    | "mutation"
    | "amplification"
    | "verification"
    | "correction"
    | "resurgence";
  claim_variant: string;
  change_summary?: string;
  publisher: string;
  title: string;
  url: string;
  evidence_id: string;
  stance: "support" | "refute" | "context";
  used_for_decision: boolean;
}

export interface RumorReport {
  schema_version:
    | "rumorbuster-report-v1"
    | "rumorbuster-report-v2"
    | "rumorbuster-report-v3";
  claim?: {
    normalized_claim: string;
    subclaims?: Array<{ id: string; text: string; material: boolean }>;
    temporality?: string;
    event_date?: string | null;
    source_url?: string | null;
    domain?:
      | "general"
      | "medical"
      | "legal"
      | "finance"
      | "science"
      | "technology"
      | "unknown";
    domain_reason?: string;
    text_risk_analysis?: {
      status: "completed" | "unavailable";
      authoritative: false;
      signals: Array<{
        dimension: string;
        level: "none" | "low" | "medium" | "high";
        spans: string[];
        note: string;
      }>;
      verification_targets: Array<{
        kind: "authority" | "number" | "date" | "causal_claim" | "entity";
        text: string;
        claim_ids: string[];
      }>;
      search_hints: string[];
    };
  } | null;
  checkability?: {
    checkability: string;
    reason: string;
  } | null;
  rag?: {
    status: string;
    matches: Array<{
      record_id: string;
      canonical_claim: string;
      similarity: number;
      historical_verdict: string;
      temporal_warning?: string | null;
    }>;
  } | null;
  classifier_signal?: {
    status: string;
    label: string;
    aggregate_label?: string;
    rationale: string;
    role?: "auxiliary_signal";
    authoritative?: false;
    model_id?: string;
    api_style?: "modelscope_chat" | "openai_chat" | string;
    subclaims?: Array<{
      claim_id: string;
      text: string;
      status: "ok" | "unavailable" | "invalid_output";
      raw_label?: string | null;
      mapped_label: "rumor" | "non_rumor" | "uncertain" | string;
      latency_ms?: number | null;
      input_hash?: string;
      request_id?: string;
      called_at?: string;
      usage?: Record<string, number>;
      error_code?: string | null;
    }>;
  } | null;
  evidence: RumorEvidenceItem[];
  decision: {
    verdict: string;
    strength: string;
    accepted_evidence_ids: string[];
    excluded_evidence: Array<{
      evidence_id: string;
      reason_code: string;
      explanation: string;
    }>;
    classifier_consistency: string;
    classifier_consistency_by_claim?: Record<string, string>;
    explanation: string;
    subclaim_decisions?: Record<string, string>;
  };
  capabilities?: Record<string, boolean>;
  domain_route?: {
    domain: string;
    reason: string;
  } | null;
  research_branches?: Record<
    string,
    {
      status: "pending" | "running" | "completed" | "skipped" | "unavailable";
      started_at?: string;
      finished_at?: string;
      duration_ms?: number;
      result_count?: number;
      error_code?: string | null;
    }
  >;
  evidence_review?: {
    status: string;
    coverage_by_claim: Record<string, string>;
    missing_claim_ids: string[];
    conflict_claim_ids: string[];
    duplicate_groups: string[];
    threshold_gap?: boolean;
    preliminary_reason_codes?: string[];
    supplement_needed: boolean;
    supplement_query: string;
    notes: string;
  } | null;
  original_page?: {
    source_url?: string | null;
    requested_url?: string | null;
    title?: string | null;
    content_chars?: number | null;
    truncated?: boolean | null;
  } | null;
  timeline?: {
    timeline_status: "ready" | "insufficient";
    events: RumorTimelineEvent[];
    note: string;
  } | null;
  limitations?: string[];
  workflow_trace?: Array<{
    tool?: string;
    status?: string;
    calls?: number;
    stage?: string;
    at?: string;
  }>;
}

export interface RumorWorkflow {
  input_message_id?: string | null;
  stage: string;
  degradation_codes?: string[];
  trace?: Array<{
    tool?: string;
    status?: string;
    calls?: number;
    stage?: string;
    at?: string;
  }>;
  branch_status?: RumorReport["research_branches"];
  run_id?: string;
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
  rumor_workflow?: RumorWorkflow | null;
  rumor_report?: RumorReport | null;
  rumor_branch_status?: RumorReport["research_branches"];
}

export interface AgentThread extends Thread<AgentThreadState> {}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
}
