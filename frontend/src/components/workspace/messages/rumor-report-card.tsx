"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  CheckCircle2Icon,
  CircleHelpIcon,
  Clock3Icon,
  DatabaseIcon,
  ExternalLinkIcon,
  MinusIcon,
  ScaleIcon,
  ShieldCheckIcon,
  XCircleIcon,
} from "lucide-react";
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
import {
  buildRumorReportViewModel,
  publicRumorLabel,
  safePublicHttpUrl,
  type RumorVerdictTone,
} from "@/core/threads/rumor-report-view";
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

const degradationLabels: Record<string, string> = {
  original_fetch_unavailable: "原网页抓取不可用",
  checkability_unavailable: "可核验性判断降级",
  rag_unavailable: "历史知识库不可用",
  rag_index_missing: "本地向量索引尚未构建，已使用TF-IDF降级检索",
  rag_index_mismatch: "向量索引与当前模型或语料版本不一致",
  rag_index_corrupt: "本地向量索引损坏",
  rag_dense_unavailable: "语义向量检索不可用，已使用关键词检索",
  rag_dense_disabled: "语义向量检索已关闭",
  research_unavailable: "独立搜索不可用",
  classifier_unavailable: "LoRA 分类服务不可用",
  adjudicator_tool_unavailable: "规则工具不可用",
  web_research_unavailable: "普通网页研究不可用",
  authority_research_unavailable: "专业权威研究不可用",
  timeline_research_unavailable: "实验性传播检索不可用",
  supplement_research_unavailable: "定向补充搜索不可用",
};

const branchLabels: Record<string, string> = {
  rag: "本地向量知识库 RAG",
  web: "普通网页研究",
  classifier: "LoRA 文本分类",
  authority: "专业权威研究",
  timeline_research: "实验性传播检索",
  supplement: "定向补充搜索",
};

const stageLabels: Record<string, string> = {
  conversation: "普通对话",
  fetch_original: "读取原网页",
  checkability: "判断可核验性",
  rag: "检索本地知识库",
  research: "搜索独立证据",
  classifier: "调用 LoRA 分类器",
  adjudicate: "执行规则裁决",
  report: "生成最终报告",
  needs_input: "等待补充主张",
  reset_input: "初始化本轮状态",
  extract_claim: "提取结构化主张",
  parallel_collection: "并行收集证据",
  evidence_normalization: "校验证据",
  evidence_review: "审查证据缺口",
  supplementary_research: "定向补充搜索",
  timeline: "整理证据序列",
  explain: "生成受约束解释",
};

const workflowSteps = [
  {
    id: "input",
    label: "输入解析",
    stages: ["reset_input", "fetch_original", "extract_claim"],
  },
  {
    id: "checkability",
    label: "可核验性",
    stages: ["checkability", "needs_input", "conversation"],
  },
  {
    id: "collection",
    label: "并行取证",
    stages: ["parallel_collection", "rag", "research", "classifier"],
  },
  {
    id: "review",
    label: "汇合校验",
    stages: [
      "evidence_normalization",
      "evidence_review",
      "supplementary_research",
    ],
  },
  { id: "adjudicate", label: "规则裁决", stages: ["adjudicate"] },
  { id: "timeline", label: "证据整理", stages: ["timeline"] },
  { id: "report", label: "解释报告", stages: ["explain", "report"] },
];

const verdictStyles: Record<
  RumorVerdictTone,
  {
    panel: string;
    badge: string;
    icon: React.ComponentType<{ className?: string }>;
  }
> = {
  danger: {
    panel: "border-rb-danger/35 bg-rb-danger/5",
    badge: "bg-rb-danger text-white",
    icon: XCircleIcon,
  },
  success: {
    panel: "border-rb-evidence/35 bg-rb-evidence/5",
    badge: "bg-rb-evidence text-white dark:text-slate-950",
    icon: CheckCircle2Icon,
  },
  warning: {
    panel: "border-rb-warning/35 bg-rb-warning/5",
    badge: "bg-rb-warning text-white dark:text-slate-950",
    icon: AlertTriangleIcon,
  },
  disputed: {
    panel: "border-violet-500/35 bg-violet-500/5",
    badge: "bg-violet-600 text-white dark:bg-violet-400 dark:text-slate-950",
    icon: CircleHelpIcon,
  },
  muted: {
    panel: "border-border bg-muted/35",
    badge: "bg-muted-foreground text-background",
    icon: CircleHelpIcon,
  },
};

function activeStep(stage: string) {
  const stages: Record<string, number> = {
    conversation: 1,
    fetch_original: 0,
    checkability: 1,
    rag: 2,
    research: 2,
    classifier: 2,
    adjudicate: 4,
    report: 6,
    needs_input: 1,
    reset_input: 0,
    extract_claim: 0,
    parallel_collection: 2,
    evidence_normalization: 3,
    evidence_review: 3,
    supplementary_research: 3,
    timeline: 5,
    explain: 6,
  };
  return stages[stage] ?? 0;
}

function BranchStatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CheckCircle2Icon className="text-rb-evidence size-4" />;
  }
  if (status === "running") {
    return <ActivityIcon className="text-rb-evidence size-4" />;
  }
  if (status === "unavailable") {
    return <AlertTriangleIcon className="text-rb-warning size-4" />;
  }
  if (status === "skipped") {
    return <MinusIcon className="text-muted-foreground size-4" />;
  }
  return <Clock3Icon className="text-muted-foreground size-4" />;
}

export function RumorWorkflowStatus({ workflow }: { workflow: RumorWorkflow }) {
  const current = activeStep(workflow.stage);

  return (
    <Card className="border-rb-evidence/20 bg-card/95 w-full shadow-lg">
      <CardContent className="space-y-4 py-5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-2 font-semibold">
            <ActivityIcon className="text-rb-evidence size-4" />
            核验进度
          </span>
          <Badge variant="secondary">
            {stageLabels[workflow.stage] ?? "未知阶段"}
          </Badge>
          {workflow.degradation_codes?.map((code) => (
            <Badge
              key={code}
              className="border-rb-warning/30 text-rb-warning"
              variant="outline"
            >
              {degradationLabels[code] ?? "能力降级"}
            </Badge>
          ))}
        </div>

        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
          {workflowSteps.map((step, index) => {
            const completed = index < current || workflow.stage === "report";
            const active = step.stages.includes(workflow.stage);
            return (
              <li
                key={step.id}
                className={cn(
                  "relative overflow-hidden rounded-xl border px-2 py-3 text-center text-xs transition-colors duration-200",
                  active &&
                    workflow.stage !== "report" &&
                    "rumor-stage-running border-rb-evidence/60 bg-rb-evidence/5 text-foreground",
                  completed && "border-rb-evidence/15 bg-rb-evidence/5",
                  !active && !completed && "text-muted-foreground",
                )}
              >
                <span className="text-muted-foreground block text-[10px] font-semibold tracking-[0.14em]">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="mt-0.5 block font-semibold">{step.label}</span>
                <span className="mt-1 block text-[11px]">
                  {active && workflow.stage !== "report"
                    ? "进行中"
                    : completed
                      ? "完成/跳过"
                      : "等待"}
                </span>
              </li>
            );
          })}
        </ol>

        {workflow.branch_status && (
          <div>
            <p className="text-muted-foreground mb-2 text-xs">
              以下分支在“并行取证”阶段同时运行，汇合后才进入规则裁决。
            </p>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {Object.entries(workflow.branch_status).map(([branch, state]) => (
                <div
                  key={branch}
                  className={cn(
                    "bg-card flex items-center justify-between gap-3 rounded-xl border px-3 py-3 text-xs",
                    state.status === "running" &&
                      "rumor-stage-running border-rb-evidence/40",
                    state.status === "unavailable" && "border-rb-warning/35",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <BranchStatusIcon status={state.status} />
                    <span className="truncate font-medium">
                      {branchLabels[branch] ?? "其他核验分支"}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block font-medium">
                      {publicRumorLabel(state.status)}
                    </span>
                    <span className="text-muted-foreground text-[10px]">
                      {state.duration_ms != null
                        ? `${state.duration_ms} ms`
                        : "未记录耗时"}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
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
  const publicUrl = safePublicHttpUrl(item.url);
  return (
    <article
      className={cn(
        "bg-card rounded-xl border p-4 shadow-sm transition-colors duration-200",
        accepted && "border-rb-evidence/35",
        excludedReason && "border-rb-warning/30",
      )}
    >
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
          {directnessLabels[item.directness] ?? "直接性未知"}
        </Badge>
        {accepted && (
          <Badge className="bg-rb-evidence text-white dark:text-slate-950">
            用于裁决
          </Badge>
        )}
        {excludedReason && <Badge variant="destructive">已排除</Badge>}
        {timelineOnly && <Badge variant="secondary">补充材料</Badge>}
      </div>

      {publicUrl ? (
        <a
          className="hover:text-rb-evidence inline-flex items-start gap-1.5 font-semibold underline decoration-current/30 underline-offset-4 transition-colors"
          href={publicUrl}
          rel="noreferrer"
          target="_blank"
        >
          <span>{item.title}</span>
          <ExternalLinkIcon className="mt-0.5 size-3.5 shrink-0" />
        </a>
      ) : (
        <p className="font-semibold">{item.title}</p>
      )}
      <p className="text-muted-foreground mt-1 text-xs">
        {item.publisher} · {item.published_at ?? "发布时间未知"} ·{" "}
        {publicRumorLabel(item.temporal_relevance)}
      </p>
      <p className="mt-2 text-sm leading-6">{item.summary}</p>
      {item.excerpt?.trim() && (
        <blockquote className="border-rb-evidence/35 bg-rb-evidence/5 mt-3 border-l-2 px-3 py-2 text-xs leading-5">
          <span className="text-muted-foreground font-medium">正文引文：</span>“
          {item.excerpt.trim()}”
        </blockquote>
      )}
      {[item.source_grade_reason, item.authority_reason].some(Boolean) && (
        <p className="text-muted-foreground mt-2 text-xs leading-5">
          {[item.source_grade_reason, item.authority_reason]
            .filter(Boolean)
            .join("；")}
        </p>
      )}
      <p className="text-muted-foreground mt-1 text-xs">
        独立来源组：{item.independent_group ?? "未确认"}
        {excludedReason ? ` · 排除原因：${excludedReason}` : ""}
      </p>
      <p className="text-muted-foreground mt-1 text-xs">
        正文状态：{publicRumorLabel(item.fetch_status)}
        {item.content_type ? ` · ${item.content_type}` : ""}
        {item.document_hash
          ? ` · 文档指纹 ${item.document_hash.slice(0, 12)}`
          : ""}
      </p>
      {(item.claim_ids?.length ?? 0) > 0 && (
        <p className="text-muted-foreground mt-1 text-xs">
          关联子主张：{item.claim_ids?.join("、")}
        </p>
      )}
    </article>
  );
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="bg-card/75 rounded-xl border px-3 py-3 shadow-sm">
      <p className="text-muted-foreground text-[11px] font-medium tracking-wide">
        {label}
      </p>
      <p className="mt-1 text-lg font-bold">{value}</p>
      {hint && <p className="text-muted-foreground text-[10px]">{hint}</p>}
    </div>
  );
}

type EvidenceFilter = "all" | "accepted" | "excluded";

export function RumorReportCard({ report }: { report: RumorReport }) {
  const view = useMemo(() => buildRumorReportViewModel(report), [report]);
  const [filter, setFilter] = useState<EvidenceFilter>(() =>
    view.acceptedEvidence.length > 0 ? "accepted" : "all",
  );
  const verdictStyle = verdictStyles[view.verdictTone];
  const VerdictIcon = verdictStyle.icon;
  const risk = report.claim?.text_risk_analysis;
  const classifierSubclaims = report.classifier_signal?.subclaims ?? [];
  const sourceUrl = safePublicHttpUrl(
    report.original_page?.source_url ?? report.claim?.source_url,
  );
  const isTimelineEvidence = (item: RumorEvidenceItem) =>
    item.timeline_only === true || view.timelineIds.has(item.id);
  const visibleEvidence = view.allEvidence.filter((item) => {
    if (filter === "accepted") return view.acceptedIds.has(item.id);
    if (filter === "excluded") return view.excludedById.has(item.id);
    return true;
  });
  const filterOptions: Array<[EvidenceFilter, string, number]> = [
    ["all", "全部", view.allEvidence.length],
    ["accepted", "用于裁决", view.acceptedEvidence.length],
    ["excluded", "被排除", view.excludedEvidence.length],
  ];

  return (
    <article className="animate-fade-in w-full">
      <Card className="border-rb-evidence/20 bg-card overflow-hidden shadow-xl">
        <CardHeader
          className={cn("border-b px-5 py-6 sm:px-7", verdictStyle.panel)}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-muted-foreground flex items-center gap-2 text-xs font-semibold tracking-[0.14em] uppercase">
              <ScaleIcon className="text-rb-evidence size-4" />
              确定性规则裁决
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{view.checkabilityLabel}</Badge>
              <Badge variant="outline">
                证据强度：{view.evidenceStrengthLabel}
              </Badge>
              <Badge variant="outline">{view.decisionStatusLabel}</Badge>
            </div>
          </div>

          <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-3xl min-w-0">
              <CardDescription className="mb-1 text-xs font-medium">
                被核验主张
              </CardDescription>
              <CardTitle className="text-xl leading-8 text-balance sm:text-2xl">
                {view.normalizedClaim}
              </CardTitle>
            </div>
            <div
              className={cn(
                "flex shrink-0 items-center gap-2 self-start rounded-2xl px-4 py-2 text-lg font-bold shadow-sm",
                verdictStyle.badge,
              )}
            >
              <VerdictIcon className="size-5" />
              {view.verdictLabel}
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricCard
              label="采用证据"
              value={view.acceptedEvidence.length}
              hint="进入规则门槛"
            />
            <MetricCard
              label="排除证据"
              value={view.excludedEvidence.length}
              hint="不参与裁决"
            />
            <MetricCard
              label="实质子主张"
              value={view.materialSubclaimCount}
              hint="逐项核验"
            />
            <MetricCard
              label="专业领域"
              value={view.domainLabel}
              hint="决定权威路由"
            />
          </div>

          <div className="border-rb-evidence/20 bg-card/70 mt-4 flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs leading-5">
            <ShieldCheckIcon className="text-rb-evidence mt-0.5 size-4 shrink-0" />
            <p>
              最终结论由证据规则生成；RAG、LoRA 和通用大模型均不能覆盖该结论。
            </p>
          </div>
        </CardHeader>

        <CardContent className="grid gap-7 px-5 py-6 sm:px-7 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="min-w-0 space-y-8">
            <section aria-labelledby="decision-explanation">
              <div className="mb-2 flex items-center gap-2">
                <ScaleIcon className="text-rb-evidence size-4" />
                <h3 id="decision-explanation" className="text-sm font-semibold">
                  裁决依据
                </h3>
              </div>
              <p className="text-sm leading-7">{report.decision.explanation}</p>
            </section>

            <section aria-labelledby="evidence-cards">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 id="evidence-cards" className="text-sm font-semibold">
                    可追溯证据
                  </h3>
                  <p className="text-muted-foreground mt-1 text-xs">
                    默认优先展示真正进入规则裁决门槛的来源。
                  </p>
                </div>
                <div
                  className="flex flex-wrap gap-1.5"
                  role="group"
                  aria-label="证据筛选"
                >
                  {filterOptions.map(([value, text, count]) => (
                    <Button
                      key={value}
                      size="sm"
                      variant={filter === value ? "default" : "outline"}
                      onClick={() => setFilter(value)}
                    >
                      {text}（{count}）
                    </Button>
                  ))}
                </div>
              </div>
              {visibleEvidence.length > 0 ? (
                <div className="grid gap-3">
                  {visibleEvidence.map((item) => (
                    <EvidenceCard
                      key={item.id}
                      item={item}
                      accepted={view.acceptedIds.has(item.id)}
                      excludedReason={view.excludedById.get(item.id)}
                      timelineOnly={
                        isTimelineEvidence(item) &&
                        !view.acceptedIds.has(item.id)
                      }
                    />
                  ))}
                </div>
              ) : (
                <div className="bg-muted/30 rounded-xl border border-dashed p-6 text-center">
                  <DatabaseIcon className="text-muted-foreground mx-auto size-5" />
                  <p className="mt-2 text-sm font-medium">
                    当前筛选条件下没有证据
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    空结果不会被补写为证据，也不会降低裁决门槛。
                  </p>
                </div>
              )}
            </section>

            <section aria-labelledby="subclaim-comparison">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <h3 id="subclaim-comparison" className="text-sm font-semibold">
                  子主张模型—证据对照
                </h3>
                <Badge
                  variant={
                    report.decision.classifier_consistency === "conflict"
                      ? "destructive"
                      : "outline"
                  }
                >
                  {publicRumorLabel(report.decision.classifier_consistency)}
                </Badge>
              </div>
              {view.subclaimRows.length > 0 ? (
                <div className="grid gap-2">
                  {view.subclaimRows.map((item) => (
                    <article
                      key={item.id}
                      className={cn(
                        "rounded-xl border p-4 text-sm",
                        item.consistency === "conflict" &&
                          "border-rb-danger/35 bg-rb-danger/5",
                        item.consistency === "consistent" &&
                          "border-rb-evidence/35 bg-rb-evidence/5",
                      )}
                    >
                      <p className="leading-6 font-semibold">{item.text}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Badge variant="outline">LoRA：{item.modelLabel}</Badge>
                        <Badge variant="outline">
                          规则：{item.ruleDecision}
                        </Badge>
                        <Badge
                          variant={
                            item.consistency === "conflict"
                              ? "destructive"
                              : "secondary"
                          }
                        >
                          {item.consistencyLabel}
                        </Badge>
                        <Badge variant="outline">
                          {item.evidenceCount} 条有效证据
                        </Badge>
                        {item.latencyMs != null && (
                          <Badge variant="outline">{item.latencyMs} ms</Badge>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="border-rb-warning/25 bg-rb-warning/5 rounded-xl border p-4 text-sm">
                  <p className="font-medium">LoRA 分类服务未返回逐子主张结果</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    该能力不可用时，证据规则仍会独立完成裁决。
                  </p>
                </div>
              )}
              <p className="text-muted-foreground mt-2 text-xs">
                LoRA 只根据文本模式输出风险标签，没有读取本轮网页证据。
              </p>
            </section>

            {report.evidence_review && (
              <section aria-labelledby="evidence-review">
                <h3 id="evidence-review" className="mb-2 text-sm font-semibold">
                  证据审查与搜索预算
                </h3>
                <div className="rounded-xl border p-4">
                  <p className="text-sm leading-6">
                    {report.evidence_review.notes}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(
                      report.evidence_review.coverage_by_claim ?? {},
                    ).map(([claimId, coverage]) => (
                      <Badge key={claimId} variant="outline">
                        {claimId}：{publicRumorLabel(coverage)}
                      </Badge>
                    ))}
                    <Badge variant="secondary">
                      两阶段检索已完成，不进行模型自由补检
                    </Badge>
                    {report.evidence_review.threshold_gap && (
                      <Badge className="bg-rb-warning text-white dark:text-slate-950">
                        裁决门槛尚未满足
                      </Badge>
                    )}
                  </div>
                </div>
              </section>
            )}

            <section aria-labelledby="evidence-chronology">
              <h3
                id="evidence-chronology"
                className="mb-2 text-sm font-semibold"
              >
                证据发布时间序列
              </h3>
              <p className="text-muted-foreground mb-4 text-xs leading-5">
                这里只按本轮实际取得材料的发布日期排序，用于比较证据新旧；不推断首发、转载关系或传播路径。
              </p>
              {view.evidenceChronology.length > 0 ? (
                <ol className="border-rb-evidence/25 ml-2 space-y-4 border-l pl-5 text-sm">
                  {view.evidenceChronology.map((item) => {
                    const publicUrl = safePublicHttpUrl(item.url);
                    const accepted = view.acceptedIds.has(item.id);
                    const excluded = view.excludedById.get(item.id);
                    return (
                      <li key={`evidence-date-${item.id}`} className="relative">
                        <span className="bg-rb-evidence ring-background absolute top-1 -left-[1.47rem] size-2.5 rounded-full ring-4" />
                        <p className="font-semibold">{item.published_at}</p>
                        <p className="text-muted-foreground text-xs">
                          {item.publisher} · {stanceLabels[item.stance]} ·{" "}
                          {item.verified_source_level ?? item.source_level}
                          级来源
                        </p>
                        {publicUrl ? (
                          <a
                            className="hover:text-rb-evidence mt-1 inline-flex items-center gap-1 underline underline-offset-4"
                            href={publicUrl}
                            rel="noreferrer"
                            target="_blank"
                          >
                            {item.title}
                            <ExternalLinkIcon className="size-3" />
                          </a>
                        ) : (
                          <p className="mt-1 font-medium">{item.title}</p>
                        )}
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Badge variant={accepted ? "default" : "outline"}>
                            {accepted ? "用于裁决" : "未用于裁决"}
                          </Badge>
                          {excluded && (
                            <Badge variant="secondary">{excluded}</Badge>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <div className="bg-muted/30 rounded-xl border border-dashed p-4 text-sm">
                  <p className="font-medium">没有可排序的发布日期</p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    证据仍保留在上方列表；系统不会猜测或补写发布时间。
                  </p>
                </div>
              )}
            </section>

            <details className="group rounded-xl border">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold">
                <span>辅助分析：RAG、文本风险与并行分支</span>
                <span className="text-muted-foreground transition-transform group-open:rotate-45">
                  ＋
                </span>
              </summary>
              <div className="space-y-6 border-t px-4 py-4">
                <section>
                  <div className="mb-2 flex items-center gap-2">
                    <DatabaseIcon className="text-rb-signal size-4" />
                    <h4 className="text-sm font-semibold">
                      本地向量知识库 RAG
                    </h4>
                    <Badge variant="outline">
                      {report.rag?.matches?.length ?? 0} 条命中
                    </Badge>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    检索相关度不是事实置信度；历史知识只提供核验线索，不参与当前主张的证据门槛。
                  </p>
                  {report.rag && (
                    <div className="text-muted-foreground mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                      <span>
                        模式：
                        {report.rag.retrieval_mode === "hybrid"
                          ? "语义＋关键词混合检索"
                          : report.rag.retrieval_mode === "sparse_fallback"
                            ? "TF-IDF降级检索"
                            : "本地检索"}
                      </span>
                      {report.rag.document_count != null && (
                        <span>文档：{report.rag.document_count}</span>
                      )}
                      {report.rag.chunk_count != null &&
                        report.rag.chunk_count > 0 && (
                          <span>片段：{report.rag.chunk_count}</span>
                        )}
                    </div>
                  )}
                  {(report.rag?.matches?.length ?? 0) > 0 && (
                    <ul className="mt-3 grid gap-2 text-sm">
                      {report.rag?.matches.map((match) => (
                        <li
                          key={
                            [
                              match.chunk_id,
                              match.document_id,
                              match.record_id,
                            ].find(Boolean) ?? match.record_id
                          }
                          className="rounded-lg border p-3"
                        >
                          <p className="font-medium">{match.canonical_claim}</p>
                          <p className="text-muted-foreground mt-1 text-xs">
                            {match.retrieval_sources?.includes("dense") &&
                            match.retrieval_sources?.includes("sparse")
                              ? "语义＋关键词命中"
                              : match.retrieval_sources?.includes("dense")
                                ? "语义命中"
                                : "关键词命中"}
                            {match.claim_ids?.length
                              ? ` · 关联 ${match.claim_ids.join("、")}`
                              : ""}
                            {` · 历史结论 ${match.historical_verdict}`}
                          </p>
                          {match.excerpt && (
                            <p className="mt-2 line-clamp-3 text-xs leading-5">
                              {match.excerpt}
                            </p>
                          )}
                          {(Boolean(match.publisher) ||
                            Boolean(match.reviewed_at)) && (
                            <p className="text-muted-foreground mt-2 text-xs">
                              {match.publisher?.trim()
                                ? match.publisher
                                : "未知发布主体"}
                              {match.published_at
                                ? ` · 发布 ${match.published_at}`
                                : ""}
                              {match.reviewed_at
                                ? ` · 复核 ${match.reviewed_at}`
                                : ""}
                            </p>
                          )}
                          {match.source_url?.startsWith("http://") ||
                          match.source_url?.startsWith("https://") ? (
                            <a
                              href={match.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-rb-evidence mt-2 block text-xs break-all underline-offset-4 hover:underline"
                            >
                              查看历史知识原始来源
                            </a>
                          ) : null}
                          {match.temporal_warning && (
                            <p className="text-rb-warning mt-2 text-xs">
                              时效提醒：{match.temporal_warning}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {(report.rag?.degradation_codes?.length ?? 0) > 0 && (
                    <p className="text-rb-warning mt-3 text-xs">
                      向量检索未完全可用，系统已安全降级：
                      {report.rag?.degradation_codes
                        ?.map((code) => degradationLabels[code] ?? code)
                        .join("、")}
                    </p>
                  )}
                </section>

                {view.branchCards.length > 0 && (
                  <section>
                    <h4 className="mb-2 text-sm font-semibold">并行核验分支</h4>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {view.branchCards.map((branch) => (
                        <div
                          key={branch.id}
                          className="rounded-lg border p-3 text-sm"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium">{branch.label}</span>
                            <Badge variant="outline">
                              {branch.statusLabel}
                            </Badge>
                          </div>
                          <p className="text-muted-foreground mt-1 text-xs">
                            {branch.durationMs != null
                              ? `${branch.durationMs} ms`
                              : "未记录耗时"}
                            {branch.resultCount != null
                              ? ` · ${branch.resultCount} 条结果`
                              : ""}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                <section>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <h4 className="text-sm font-semibold">文本风险分析</h4>
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
                              className="rounded-lg border p-3 text-sm"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium">
                                  {riskDimensionLabels[item.dimension] ??
                                    "其他文本风险"}
                                </span>
                                <Badge variant="outline">
                                  {publicRumorLabel(item.level)}
                                </Badge>
                              </div>
                              {item.spans.length > 0 && (
                                <p className="mt-1">
                                  “{item.spans.join("”；“")}”
                                </p>
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
                              {targetKindLabels[target.kind] ?? "核验目标"}：
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
              </div>
            </details>

            <details className="group rounded-xl border">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold">
                <span>技术审计与能力降级</span>
                <span className="text-muted-foreground transition-transform group-open:rotate-45">
                  ＋
                </span>
              </summary>
              <div className="space-y-5 border-t px-4 py-4 text-sm">
                <div className="grid gap-2 sm:grid-cols-2">
                  <span>报告版本：{report.schema_version}</span>
                  <span>
                    主张时态：{publicRumorLabel(report.claim?.temporality)}
                  </span>
                  <span>
                    时态依据：{report.claim?.temporality_basis ?? "未记录"}
                  </span>
                  <span>判定状态：{view.decisionStatusLabel}</span>
                  <span>
                    LoRA 模型：{report.classifier_signal?.model_id ?? "未配置"}
                  </span>
                  <span>
                    API 类型：{report.classifier_signal?.api_style ?? "未配置"}
                  </span>
                  <span>
                    分类状态：
                    {publicRumorLabel(report.classifier_signal?.status)}
                  </span>
                  <span>分类调用数：{classifierSubclaims.length}</span>
                  <span>
                    总耗时：
                    {classifierSubclaims.reduce(
                      (total, item) => total + (item.latency_ms ?? 0),
                      0,
                    )}{" "}
                    ms
                  </span>
                </div>

                {report.research_plan_summary && (
                  <div>
                    <p className="mb-2 font-medium">确定性研究计划</p>
                    <div className="text-muted-foreground grid gap-2 text-xs">
                      <p>
                        权威目标：
                        {report.research_plan_summary.authority_targets?.length
                          ? report.research_plan_summary.authority_targets
                              .map(
                                (target) =>
                                  `${target.organization}（${target.domains.join("、")}）`,
                              )
                              .join("；")
                          : "未匹配到受控机构"}
                      </p>
                      <p className="break-all">
                        发现查询：
                        {report.research_plan_summary.queries?.discovery ??
                          "未记录"}
                      </p>
                      <p className="break-all">
                        权威查询：
                        {report.research_plan_summary.queries?.authority ??
                          "未生成"}
                      </p>
                    </div>
                  </div>
                )}

                {report.workflow_trace?.length ? (
                  <div>
                    <p className="mb-2 font-medium">工作流 trace</p>
                    <ol className="text-muted-foreground space-y-1 text-xs">
                      {report.workflow_trace.map((item, index) => (
                        <li
                          key={`${item.tool ?? item.stage ?? "trace"}-${index}`}
                        >
                          {item.stage
                            ? (stageLabels[item.stage] ?? "未知阶段")
                            : `${item.tool ?? "未知工具"} · ${publicRumorLabel(item.status)} · ${item.calls ?? 0} 次`}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : (
                  <p className="text-muted-foreground text-xs">
                    历史报告未记录调用链。
                  </p>
                )}

                {view.limitations.length > 0 && (
                  <div>
                    <p className="mb-2 font-medium">本轮能力降级</p>
                    <ul className="list-disc space-y-1 pl-5 text-xs">
                      {view.limitations.map((item) => (
                        <li key={item}>
                          {degradationLabels[item] ?? "未识别的能力降级"}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </details>
          </div>

          <aside className="bg-background/70 h-fit space-y-5 rounded-xl border p-4 lg:sticky lg:top-16">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <ShieldCheckIcon className="text-rb-evidence size-4" />
                <h3 className="text-sm font-semibold">可信边界</h3>
              </div>
              <ol className="text-muted-foreground space-y-2 text-xs leading-5">
                <li>1. 模型负责提取与解释</li>
                <li>2. RAG 只召回历史相似记录</li>
                <li>3. 网页工具收集当前证据</li>
                <li>4. 规则引擎决定最终结论</li>
              </ol>
            </div>

            <div className="border-t pt-4 text-sm">
              <p className="font-medium">原网页</p>
              {sourceUrl ? (
                <a
                  className="text-muted-foreground hover:text-rb-evidence mt-1 inline-flex max-w-full items-start gap-1 break-all underline underline-offset-4"
                  href={sourceUrl}
                  rel="noreferrer"
                  target="_blank"
                >
                  <span>{report.original_page?.title ?? "打开来源页面"}</span>
                  <ExternalLinkIcon className="mt-0.5 size-3.5 shrink-0" />
                </a>
              ) : (
                <p className="text-muted-foreground mt-1">未提供或 URL 无效</p>
              )}
            </div>

            <div className="border-t pt-4 text-sm">
              <p className="font-medium">RAG 历史命中</p>
              <p className="text-muted-foreground mt-1">
                {report.rag?.matches?.length ?? 0} 条，仅作相似记录参考
              </p>
            </div>

            <div className="border-t pt-4 text-sm">
              <p className="font-medium">评论质证</p>
              <p className="text-muted-foreground mt-1">
                {report.capabilities?.social_context
                  ? "已启用"
                  : "未启用；评论不参与证据裁决"}
              </p>
            </div>

            <div className="border-t pt-4 text-sm">
              <p className="font-medium">导出</p>
              <p className="text-muted-foreground mt-1">
                顶部“导出”提供正式 Markdown、JSON 和打印报告。
              </p>
            </div>
          </aside>
        </CardContent>
      </Card>
    </article>
  );
}
