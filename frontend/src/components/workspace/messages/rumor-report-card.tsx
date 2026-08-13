"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  RumorEvidenceItem,
  RumorReport,
  RumorWorkflow,
} from "@/core/threads/types";
import { cn } from "@/lib/utils";

const stanceLabels: Record<RumorEvidenceItem["stance"], string> = {
  support: "支持",
  refute: "反驳",
  context: "背景",
};

const directnessLabels: Record<string, string> = {
  direct: "直接证据",
  indirect: "间接证据",
  snippet_only: "仅搜索摘要",
};

const statusLabels: Record<string, string> = {
  checkable_now: "当前可核验",
  checkable_later: "需等待事实发生",
  not_a_factual_claim: "非事实表达",
  not_publicly_checkable: "非公开事实",
  needs_clarification: "需要补充信息",
  event_match: "与事件时间匹配",
  current: "当前有效",
  stale: "可能过时",
  unknown: "状态未知",
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
  rumor: "疑似谣言",
  non_rumor: "疑似非谣言",
};

const riskDimensionLabels: Record<string, string> = {
  emotional_manipulation: "情绪操纵",
  exaggeration: "夸张表达",
  absolute_claim: "绝对化断言",
  forwarding_pressure: "转发压力",
  internal_contradiction: "内部矛盾",
  possible_common_sense_conflict: "疑似常识冲突",
};

const targetKindLabels: Record<string, string> = {
  authority: "机构/专家",
  number: "数字",
  date: "日期",
  causal_claim: "因果关系",
  entity: "实体",
};

const eventTypeLabels: Record<string, string> = {
  earliest_found: "本轮最早检索记录",
  spread: "传播",
  mutation: "变体",
  amplification: "放大传播",
  verification: "核验",
  correction: "更正",
  resurgence: "再次传播",
};

const degradationLabels: Record<string, string> = {
  original_fetch_unavailable: "原网页抓取不可用",
  checkability_unavailable: "可核验性判断降级",
  rag_unavailable: "历史知识库不可用",
  research_unavailable: "独立搜索不可用",
  classifier_unavailable: "微调分类器不可用",
  adjudicator_tool_unavailable: "规则工具不可用",
  web_research_unavailable: "普通网页研究不可用",
  authority_research_unavailable: "专业权威研究不可用",
  supplement_research_unavailable: "定向补充搜索不可用",
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
  classifier: "微调分类器",
  authority: "专业权威研究",
  supplement: "定向补充搜索",
};

function label(value: string | null | undefined) {
  if (!value) return "未知";
  return statusLabels[value] ?? value;
}

function EvidenceCard({
  item,
  accepted,
  excludedReason,
  timelineOnly,
}: {
  item: RumorEvidenceItem;
  accepted: boolean;
  excludedReason?: string;
  timelineOnly: boolean;
}) {
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge variant={item.stance === "refute" ? "destructive" : "secondary"}>
          {stanceLabels[item.stance]}
        </Badge>
        <Badge variant="outline">
          {item.verified_source_level ?? item.source_level}级来源
        </Badge>
        {item.claimed_source_level &&
          item.claimed_source_level !==
            (item.verified_source_level ?? item.source_level) && (
            <Badge variant="outline">
              模型声明 {item.claimed_source_level}级
            </Badge>
          )}
        <Badge variant="outline">
          {directnessLabels[item.directness] ?? item.directness}
        </Badge>
        {accepted && <Badge>用于裁决</Badge>}
        {excludedReason && <Badge variant="destructive">已排除</Badge>}
        {timelineOnly && <Badge variant="secondary">仅传播记录</Badge>}
      </div>
      <a
        className="font-medium underline underline-offset-4"
        href={item.url}
        rel="noreferrer"
        target="_blank"
      >
        {item.title}
      </a>
      <p className="text-muted-foreground mt-1 text-xs">
        {item.publisher} · {item.published_at ?? "发布时间未知"} ·{" "}
        {label(item.temporal_relevance)}
      </p>
      <p className="mt-2 text-sm leading-6">{item.summary}</p>
      {[item.source_grade_reason, item.authority_reason].some(Boolean) && (
        <p className="text-muted-foreground mt-2 text-xs">
          {[item.source_grade_reason, item.authority_reason]
            .filter(Boolean)
            .join("；")}
        </p>
      )}
      <p className="text-muted-foreground mt-1 text-xs">
        独立来源组：{item.independent_group ?? "未确认"}
        {excludedReason ? ` · 排除原因：${excludedReason}` : ""}
      </p>
    </div>
  );
}

const workflowSteps = [
  {
    id: "claim",
    label: "主张提取",
    tools: ["web_fetch", "classify_checkability"],
  },
  { id: "rag", label: "RAG", tools: ["retrieve_verified_rumors"] },
  { id: "research", label: "搜索", tools: ["task"] },
  { id: "classifier", label: "分类器", tools: ["rumor_check"] },
  { id: "adjudicate", label: "裁决", tools: ["assess_evidence"] },
  { id: "timeline", label: "时间线", tools: [] },
  { id: "report", label: "报告", tools: [] },
];

const stageLabels: Record<string, string> = {
  conversation: "普通对话",
  fetch_original: "读取原网页",
  checkability: "判断可核验性",
  rag: "检索历史谣言",
  research: "搜索独立证据",
  classifier: "调用微调分类器",
  adjudicate: "执行规则裁决",
  report: "生成最终报告",
  needs_input: "等待补充主张",
  reset_input: "初始化本轮状态",
  extract_claim: "提取结构化主张",
  parallel_collection: "并行收集证据",
  evidence_normalization: "校验证据",
  evidence_review: "审查证据缺口",
  supplementary_research: "定向补充搜索",
  timeline: "构建时间线",
  explain: "生成受约束解释",
};

function activeStep(stage: string) {
  const stages: Record<string, number> = {
    conversation: 0,
    fetch_original: 0,
    checkability: 0,
    rag: 1,
    research: 2,
    classifier: 3,
    adjudicate: 4,
    report: 6,
    needs_input: 0,
    reset_input: 0,
    extract_claim: 0,
    parallel_collection: 2,
    evidence_normalization: 4,
    evidence_review: 4,
    supplementary_research: 2,
    timeline: 5,
    explain: 6,
  };
  return stages[stage] ?? 0;
}

export function RumorWorkflowStatus({ workflow }: { workflow: RumorWorkflow }) {
  const current = activeStep(workflow.stage);
  const called = new Map(
    workflow.trace?.flatMap((item) =>
      item.tool && item.status ? [[item.tool, item.status] as const] : [],
    ),
  );

  return (
    <Card className="w-full border-dashed">
      <CardContent className="space-y-3 py-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">核验进度：</span>
          <Badge variant="secondary">
            {stageLabels[workflow.stage] ?? workflow.stage}
          </Badge>
          {workflow.degradation_codes?.map((code) => (
            <Badge key={code} variant="outline">
              {degradationLabels[code] ?? `降级：${code}`}
            </Badge>
          ))}
        </div>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {workflowSteps.map((step, index) => {
            const toolStatuses = step.tools
              .map((tool) => called.get(tool))
              .filter(Boolean);
            const completed = index < current || workflow.stage === "report";
            const degraded = toolStatuses.includes("degraded");
            return (
              <li
                key={step.id}
                className={cn(
                  "rounded-md border px-2 py-2 text-center text-xs",
                  index === current && workflow.stage !== "report"
                    ? "border-blue-500 bg-blue-500/10"
                    : completed
                      ? "bg-muted"
                      : "text-muted-foreground",
                )}
              >
                <span className="block font-medium">{step.label}</span>
                <span>
                  {degraded ? "降级" : completed ? "完成/跳过" : "等待"}
                </span>
              </li>
            );
          })}
        </ol>
        {workflow.branch_status && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(workflow.branch_status).map(([branch, state]) => (
              <div
                key={branch}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-xs"
              >
                <span>{branchLabels[branch] ?? branch}</span>
                <Badge variant="outline">{label(state.status)}</Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type EvidenceFilter = "all" | "accepted" | "excluded" | "timeline";

export function RumorReportCard({ report }: { report: RumorReport }) {
  const [filter, setFilter] = useState<EvidenceFilter>("all");
  const evidence = report.evidence ?? [];
  const accepted = useMemo(
    () => new Set(report.decision.accepted_evidence_ids ?? []),
    [report.decision.accepted_evidence_ids],
  );
  const excluded = useMemo(
    () =>
      new Map(
        (report.decision.excluded_evidence ?? []).map((item) => [
          item.evidence_id,
          item.explanation,
        ]),
      ),
    [report.decision.excluded_evidence],
  );
  const timeline = useMemo(
    () => report.timeline?.events ?? [],
    [report.timeline?.events],
  );
  const timelineEvidence = useMemo(
    () => new Set(timeline.map((item) => item.evidence_id)),
    [timeline],
  );
  const visibleEvidence = evidence.filter((item) => {
    if (filter === "accepted") return accepted.has(item.id);
    if (filter === "excluded") return excluded.has(item.id);
    if (filter === "timeline") {
      return timelineEvidence.has(item.id) && !accepted.has(item.id);
    }
    return true;
  });
  const conflict = report.decision.classifier_consistency === "conflict";
  const risk = report.claim?.text_risk_analysis;
  const classifierSubclaims = report.classifier_signal?.subclaims ?? [];
  const claimText = new Map(
    (report.claim?.subclaims ?? []).map((item) => [item.id, item.text]),
  );
  const evidenceCountByClaim = evidence.reduce<Record<string, number>>(
    (counts, item) => {
      for (const claimId of item.claim_ids ?? []) {
        counts[claimId] = (counts[claimId] ?? 0) + 1;
      }
      return counts;
    },
    {},
  );

  return (
    <Card className="w-full border-blue-500/30 bg-blue-500/5">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>结构化核验结果</CardTitle>
          <Badge
            variant={
              report.decision.verdict === "谣言" ? "destructive" : "default"
            }
          >
            {report.decision.verdict}
          </Badge>
          <Badge variant="outline">
            证据强度：{label(report.decision.strength)}
          </Badge>
        </div>
        <CardDescription>
          {label(report.checkability?.checkability)} · {report.schema_version}
          {report.domain_route
            ? ` · ${domainLabels[report.domain_route.domain] ?? report.domain_route.domain}`
            : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0 space-y-6">
          <section>
            <h3 className="mb-2 text-sm font-semibold">规则解释</h3>
            <p className="text-sm leading-6">{report.decision.explanation}</p>
          </section>

          <section>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">文本风险分析</h3>
              <Badge variant="outline">文本风险不等于事实为假</Badge>
            </div>
            {risk?.status === "completed" ? (
              <div className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-2">
                  {risk.signals
                    .filter((item) => item.level !== "none")
                    .map((item) => (
                      <div
                        key={item.dimension}
                        className="rounded-md border p-3 text-sm"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">
                            {riskDimensionLabels[item.dimension] ??
                              item.dimension}
                          </span>
                          <Badge variant="outline">{item.level}</Badge>
                        </div>
                        {item.spans.length > 0 && (
                          <p className="mt-1">“{item.spans.join("”；“")}”</p>
                        )}
                        {item.note && (
                          <p className="text-muted-foreground mt-1 text-xs">
                            {item.note}
                          </p>
                        )}
                      </div>
                    ))}
                </div>
                {risk.verification_targets.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {risk.verification_targets.map((target, index) => (
                      <Badge
                        key={`${target.kind}-${target.text}-${index}`}
                        variant="secondary"
                      >
                        {targetKindLabels[target.kind] ?? target.kind}：
                        {target.text}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                本轮文本风险提取不可用，不影响事实核验。
              </p>
            )}
          </section>

          {report.research_branches && (
            <section>
              <h3 className="mb-2 text-sm font-semibold">并行核验分支</h3>
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(report.research_branches).map(
                  ([branch, state]) => (
                    <div key={branch} className="rounded-md border p-3 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">
                          {branchLabels[branch] ?? branch}
                        </span>
                        <Badge variant="outline">{label(state.status)}</Badge>
                      </div>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {state.duration_ms != null
                          ? `${state.duration_ms} ms`
                          : "未记录耗时"}
                        {state.result_count != null
                          ? ` · ${state.result_count} 条结果`
                          : ""}
                      </p>
                    </div>
                  ),
                )}
              </div>
            </section>
          )}

          {report.evidence_review && (
            <section>
              <h3 className="mb-2 text-sm font-semibold">证据审查</h3>
              <p className="text-sm leading-6">
                {report.evidence_review.notes}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(
                  report.evidence_review.coverage_by_claim ?? {},
                ).map(([claimId, coverage]) => (
                  <Badge key={claimId} variant="outline">
                    {claimId}：{label(coverage)}
                  </Badge>
                ))}
                <Badge variant="secondary">
                  {report.evidence_review.supplement_needed
                    ? "已申请一次补检"
                    : "无需或不可继续补检"}
                </Badge>
                {report.evidence_review.threshold_gap && (
                  <Badge variant="destructive">裁决门槛尚未满足</Badge>
                )}
              </div>
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center gap-2">
              <h3 className="text-sm font-semibold">子主张模型—证据对照</h3>
              <Badge variant={conflict ? "destructive" : "outline"}>
                {label(report.decision.classifier_consistency)}
              </Badge>
            </div>
            {classifierSubclaims.length > 0 ? (
              <div className="grid gap-2">
                {classifierSubclaims.map((item) => {
                  const consistency =
                    report.decision.classifier_consistency_by_claim?.[
                      item.claim_id
                    ] ?? "not_comparable";
                  return (
                    <div
                      key={item.claim_id}
                      className={cn(
                        "rounded-md border p-3 text-sm",
                        consistency === "conflict" &&
                          "border-red-500/50 bg-red-500/5",
                        consistency === "consistent" &&
                          "border-green-500/50 bg-green-500/5",
                      )}
                    >
                      <p className="font-medium">
                        {claimText.get(item.claim_id) ?? item.text}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Badge variant="outline">
                          LoRA：{label(item.mapped_label)}
                        </Badge>
                        <Badge variant="outline">
                          规则：
                          {label(
                            report.decision.subclaim_decisions?.[item.claim_id],
                          )}
                        </Badge>
                        <Badge
                          variant={
                            consistency === "conflict"
                              ? "destructive"
                              : "secondary"
                          }
                        >
                          {label(consistency)}
                        </Badge>
                        <Badge variant="outline">
                          {item.latency_ms ?? 0} ms
                        </Badge>
                        <Badge variant="outline">
                          {evidenceCountByClaim[item.claim_id] ?? 0} 条证据
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                微调模型未配置或不可用；该状态不会改变证据规则结论。
              </p>
            )}
            <p className="text-muted-foreground mt-2 text-xs">
              {report.classifier_signal?.rationale ??
                "模型仅根据文本模式输出风险标签，没有读取本轮网页证据。"}
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold">模型调用审计</h3>
            <div className="grid gap-2 rounded-md border p-3 text-sm sm:grid-cols-2">
              <span>
                模型：{report.classifier_signal?.model_id ?? "未配置"}
              </span>
              <span>
                API：{report.classifier_signal?.api_style ?? "未配置"}
              </span>
              <span>状态：{label(report.classifier_signal?.status)}</span>
              <span>调用数：{classifierSubclaims.length}</span>
              <span>
                总耗时：
                {classifierSubclaims.reduce(
                  (total, item) => total + (item.latency_ms ?? 0),
                  0,
                )}{" "}
                ms
              </span>
              <span>
                调用时间：
                {classifierSubclaims[0]?.called_at
                  ? new Date(classifierSubclaims[0].called_at).toLocaleString()
                  : "无"}
              </span>
            </div>
          </section>

          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">证据卡片</h3>
              <div className="flex flex-wrap gap-1">
                {(
                  [
                    ["all", "全部"],
                    ["accepted", "用于裁决"],
                    ["excluded", "被排除"],
                    ["timeline", "传播记录"],
                  ] as Array<[EvidenceFilter, string]>
                ).map(([value, text]) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={filter === value ? "default" : "outline"}
                    onClick={() => setFilter(value)}
                  >
                    {text}
                  </Button>
                ))}
              </div>
            </div>
            {visibleEvidence.length ? (
              <div className="grid gap-3">
                {visibleEvidence.map((item) => (
                  <EvidenceCard
                    key={item.id}
                    item={item}
                    accepted={accepted.has(item.id)}
                    excludedReason={excluded.get(item.id)}
                    timelineOnly={
                      timelineEvidence.has(item.id) && !accepted.has(item.id)
                    }
                  />
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">
                当前筛选条件下没有证据。
              </p>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold">被排除证据</h3>
            {(report.decision.excluded_evidence ?? []).length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {(report.decision.excluded_evidence ?? []).map((item) => (
                  <li key={`${item.evidence_id}-${item.reason_code}`}>
                    {item.evidence_id}：{item.explanation}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-sm">无</p>
            )}
          </section>

          {report.timeline?.timeline_status === "ready" &&
            timeline.length >= 3 && (
              <section>
                <h3 className="mb-2 text-sm font-semibold">传播演化时间线</h3>
                <ol className="border-muted ml-2 space-y-3 border-l pl-4 text-sm">
                  {timeline.map((item) => (
                    <li key={`timeline-${item.id}`}>
                      <span className="font-medium">{item.date}</span>
                      <span className="text-muted-foreground">
                        {" "}
                        · {item.publisher} ·{" "}
                        {eventTypeLabels[item.event_type] ?? item.event_type}
                      </span>
                      <a
                        className="block underline underline-offset-4"
                        href={item.url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {item.title}
                      </a>
                      <p>{item.claim_variant}</p>
                      <Badge variant="outline">
                        {item.used_for_decision ? "用于裁决" : "仅作传播记录"}
                      </Badge>
                    </li>
                  ))}
                </ol>
                <p className="text-muted-foreground mt-2 text-xs">
                  {report.timeline.note}
                </p>
              </section>
            )}
          {report.timeline?.timeline_status === "insufficient" && (
            <section>
              <h3 className="mb-2 text-sm font-semibold">传播演化时间线</h3>
              <p className="text-muted-foreground text-sm">
                {report.timeline.note ?? "可追溯节点不足，本轮不生成时间线。"}
              </p>
            </section>
          )}

          {report.limitations && report.limitations.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold">本轮能力降级</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {report.limitations.map((item) => (
                  <li key={item}>{degradationLabels[item] ?? item}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="bg-background/70 h-fit space-y-4 rounded-lg border p-4 lg:sticky lg:top-16">
          <h3 className="text-sm font-semibold">核验材料</h3>
          <div className="text-sm">
            <p className="font-medium">原网页</p>
            {report.original_page?.source_url || report.claim?.source_url ? (
              <a
                className="text-muted-foreground break-all underline underline-offset-4"
                href={
                  report.original_page?.source_url ??
                  report.claim?.source_url ??
                  undefined
                }
                rel="noreferrer"
                target="_blank"
              >
                {report.original_page?.title ?? "打开来源页面"}
              </a>
            ) : (
              <p className="text-muted-foreground">未提供</p>
            )}
          </div>
          <div className="text-sm">
            <p className="font-medium">RAG 历史命中</p>
            <p className="text-muted-foreground">
              {report.rag?.matches?.length ?? 0} 条，仅作相似记录参考
            </p>
          </div>
          <div className="text-sm">
            <p className="font-medium">评论质证</p>
            <p className="text-muted-foreground">
              {report.capabilities?.social_context
                ? "已启用"
                : "未启用；评论不参与证据裁决"}
            </p>
          </div>
          <div className="text-sm">
            <p className="font-medium">工具调用</p>
            {report.workflow_trace?.length ? (
              <ul className="text-muted-foreground mt-1 space-y-1">
                {report.workflow_trace.map((item, index) => (
                  <li key={`${item.tool ?? item.stage ?? "trace"}-${index}`}>
                    {item.stage
                      ? (stageLabels[item.stage] ?? item.stage)
                      : `${item.tool} · ${label(item.status)} · ${item.calls} 次`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">历史报告未记录调用链</p>
            )}
          </div>
          <div className="text-sm">
            <p className="font-medium">导出</p>
            <p className="text-muted-foreground">
              顶部“导出”支持 Markdown、JSON 和打印。
            </p>
          </div>
        </aside>
      </CardContent>
    </Card>
  );
}
