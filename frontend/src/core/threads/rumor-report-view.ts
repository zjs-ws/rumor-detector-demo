import type {
  RumorEvidenceItem,
  RumorReport,
  RumorTimelineEvent,
} from "./types";

export type RumorVerdictKey =
  | "rumor"
  | "non_rumor"
  | "misleading"
  | "disputed"
  | "insufficient"
  | "not_checkable"
  | "unknown";

export type RumorVerdictTone =
  | "danger"
  | "success"
  | "warning"
  | "disputed"
  | "muted";

export interface RumorBranchView {
  id: string;
  label: string;
  status: string;
  statusLabel: string;
  durationMs: number | null;
  resultCount: number | null;
  errorCode: string | null;
}

export interface RumorSubclaimView {
  id: string;
  text: string;
  modelLabel: string;
  modelStatus: string;
  ruleDecision: string;
  consistency: string;
  consistencyLabel: string;
  evidenceCount: number;
  latencyMs: number | null;
}

export interface RumorReportViewModel {
  schemaVersion: RumorReport["schema_version"];
  normalizedClaim: string;
  verdictKey: RumorVerdictKey;
  verdictLabel: string;
  verdictTone: RumorVerdictTone;
  checkabilityLabel: string;
  domainLabel: string;
  evidenceStrengthLabel: string;
  acceptedEvidence: RumorEvidenceItem[];
  excludedEvidence: Array<{
    evidence: RumorEvidenceItem | null;
    evidenceId: string;
    reasonCode: string;
    explanation: string;
  }>;
  timelineEvidence: RumorEvidenceItem[];
  timelineEvents: RumorTimelineEvent[];
  branchCards: RumorBranchView[];
  subclaimRows: RumorSubclaimView[];
  limitations: string[];
  allEvidence: RumorEvidenceItem[];
  acceptedIds: Set<string>;
  excludedById: Map<string, string>;
  timelineIds: Set<string>;
  materialSubclaimCount: number;
}

const publicLabels: Record<string, string> = {
  checkable_now: "当前可核验",
  checkable_later: "需等待事实发生",
  not_a_factual_claim: "非事实表达",
  not_publicly_checkable: "非公开事实",
  needs_clarification: "需要补充信息",
  event_match: "与事件时间匹配",
  current: "当前有效",
  stale: "可能过时",
  unknown: "未知状态",
  insufficient: "证据不足",
  ready: "可展示",
  consistent: "与证据一致",
  conflict: "与证据冲突",
  unavailable: "不可用",
  skipped: "已跳过",
  not_applicable: "不适用",
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  covered: "已覆盖",
  missing: "缺少证据",
  conflicting: "存在冲突",
  partial: "部分可用",
  uncertain: "不确定",
  not_comparable: "不可比较",
  unavailable_or_uncertain: "不可用或不确定",
  rumor: "谣言风险",
  non_rumor: "非谣言风险",
  low: "低",
  medium: "中",
  high: "高",
  strong: "强",
  weak: "弱",
  mixed: "混合标签",
};

const domainLabels: Record<string, string> = {
  general: "通用事实",
  medical: "医学健康",
  legal: "法律法规",
  finance: "金融经济",
  science: "自然科学",
  technology: "技术工程",
  unknown: "领域未知",
};

const branchLabels: Record<string, string> = {
  rag: "历史谣言 RAG",
  web: "普通网页研究",
  classifier: "LoRA 文本分类",
  authority: "专业权威研究",
  supplement: "定向补充搜索",
};

export function publicRumorLabel(value: string | null | undefined): string {
  if (!value) return "未知状态";
  return publicLabels[value] ?? "未知状态";
}

export function normalizeRumorVerdict(value: string | null | undefined): {
  key: RumorVerdictKey;
  label: string;
  tone: RumorVerdictTone;
} {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "谣言" || normalized === "rumor") {
    return { key: "rumor", label: "谣言", tone: "danger" };
  }
  if (
    normalized === "非谣言" ||
    normalized === "non_rumor" ||
    normalized === "non-rumor"
  ) {
    return { key: "non_rumor", label: "非谣言", tone: "success" };
  }
  if (normalized === "误导" || normalized === "misleading") {
    return { key: "misleading", label: "误导", tone: "warning" };
  }
  if (
    normalized === "存疑" ||
    normalized === "disputed" ||
    normalized === "conflicting"
  ) {
    return { key: "disputed", label: "存疑", tone: "disputed" };
  }
  if (
    normalized === "证据不足" ||
    normalized === "insufficient" ||
    normalized === "insufficient_evidence"
  ) {
    return { key: "insufficient", label: "证据不足", tone: "warning" };
  }
  if (
    normalized === "暂不可核验" ||
    normalized === "非事实性表达" ||
    normalized === "非事实表达" ||
    normalized === "not_checkable" ||
    normalized === "not-checkable"
  ) {
    return {
      key: "not_checkable",
      label:
        normalized === "非事实性表达" || normalized === "非事实表达"
          ? "非事实表达"
          : "暂不可核验",
      tone: "muted",
    };
  }
  return { key: "unknown", label: "未知结论", tone: "muted" };
}

export function safePublicHttpUrl(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function buildRumorReportViewModel(
  report: RumorReport,
): RumorReportViewModel {
  const evidence = Array.isArray(report.evidence) ? report.evidence : [];
  const evidenceById = new Map(evidence.map((item) => [item.id, item]));
  const acceptedIds = new Set(report.decision?.accepted_evidence_ids ?? []);
  const excludedItems = report.decision?.excluded_evidence ?? [];
  const excludedById = new Map(
    excludedItems.map((item) => [item.evidence_id, item.explanation]),
  );
  const rawTimeline =
    report.timeline?.timeline_status === "ready" &&
    (report.timeline.events?.length ?? 0) >= 3
      ? report.timeline.events
      : [];
  const timelineIds = new Set(rawTimeline.map((item) => item.evidence_id));
  const acceptedEvidence = evidence.filter((item) => acceptedIds.has(item.id));
  const timelineEvidence = evidence.filter((item) => timelineIds.has(item.id));
  const verdict = normalizeRumorVerdict(report.decision?.verdict);
  const claimText = new Map(
    (report.claim?.subclaims ?? []).map((item) => [item.id, item.text]),
  );
  const classifierSubclaims = report.classifier_signal?.subclaims ?? [];
  const acceptedEvidenceCountByClaim = acceptedEvidence.reduce<
    Record<string, number>
  >((counts, item) => {
    for (const claimId of item.claim_ids ?? []) {
      counts[claimId] = (counts[claimId] ?? 0) + 1;
    }
    return counts;
  }, {});

  return {
    schemaVersion: report.schema_version,
    normalizedClaim: report.claim?.normalized_claim?.trim()
      ? report.claim.normalized_claim.trim()
      : "未提供规范化主张",
    verdictKey: verdict.key,
    verdictLabel: verdict.label,
    verdictTone: verdict.tone,
    checkabilityLabel: publicRumorLabel(
      report.checkability?.checkability ?? null,
    ),
    domainLabel:
      domainLabels[report.domain_route?.domain ?? report.claim?.domain ?? ""] ??
      "领域未知",
    evidenceStrengthLabel: publicRumorLabel(report.decision?.strength),
    acceptedEvidence,
    excludedEvidence: excludedItems.map((item) => ({
      evidence: evidenceById.get(item.evidence_id) ?? null,
      evidenceId: item.evidence_id,
      reasonCode: item.reason_code,
      explanation: item.explanation,
    })),
    timelineEvidence,
    timelineEvents: rawTimeline,
    branchCards: Object.entries(report.research_branches ?? {}).map(
      ([id, branch]) => ({
        id,
        label: branchLabels[id] ?? "其他核验分支",
        status: branch.status,
        statusLabel: publicRumorLabel(branch.status),
        durationMs: branch.duration_ms ?? null,
        resultCount: branch.result_count ?? null,
        errorCode: branch.error_code ?? null,
      }),
    ),
    subclaimRows: classifierSubclaims.map((item) => {
      const consistency =
        report.decision?.classifier_consistency_by_claim?.[item.claim_id] ??
        "not_comparable";
      const mappedLabel =
        item.mapped_label === "rumor" ||
        item.mapped_label === "non_rumor" ||
        item.mapped_label === "uncertain" ||
        item.mapped_label === "mixed"
          ? publicRumorLabel(item.mapped_label)
          : "无效模型输出";
      return {
        id: item.claim_id,
        text: claimText.get(item.claim_id) ?? item.text ?? "未提供子主张",
        modelLabel: mappedLabel,
        modelStatus: publicRumorLabel(item.status),
        ruleDecision:
          report.decision?.subclaim_decisions?.[item.claim_id] ?? "不可比较",
        consistency,
        consistencyLabel: publicRumorLabel(consistency),
        evidenceCount: acceptedEvidenceCountByClaim[item.claim_id] ?? 0,
        latencyMs: item.latency_ms ?? null,
      };
    }),
    limitations: report.limitations ?? [],
    allEvidence: evidence,
    acceptedIds,
    excludedById,
    timelineIds,
    materialSubclaimCount: (report.claim?.subclaims ?? []).filter(
      (item) => item.material,
    ).length,
  };
}
