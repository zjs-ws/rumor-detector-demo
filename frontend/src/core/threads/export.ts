import type { Message } from "@langchain/langgraph-sdk";

import {
  publicConversation,
  redactPublicText,
  sanitizePublicValue,
} from "./export-safety";
import {
  buildRumorReportViewModel,
  safePublicHttpUrl,
} from "./rumor-report-view";
import type { AgentThread, RumorReport, RumorWorkflow } from "./types";
import { titleOfThread } from "./utils";

function lineValue(value: string | null | undefined, fallback = "未提供") {
  const normalized = value?.trim();
  if (!normalized) return redactPublicText(fallback);
  return redactPublicText(normalized);
}

export function formatRumorReportAsMarkdown(
  report: RumorReport,
  metadata: {
    title?: string;
    threadId?: string;
    createdAt?: string;
    exportedAt?: string;
    degradationCodes?: string[];
  } = {},
): string {
  const view = buildRumorReportViewModel(report);
  const lines: string[] = [
    `# ${lineValue(metadata.title, "RumorBuster 核验报告")}`,
    "",
    "> 本报告的最终结论由证据规则生成；历史 RAG、LoRA 文本分类和通用大模型均不能覆盖规则结论。",
    "",
    "## 核验摘要",
    "",
    `- 输入主张：${view.normalizedClaim}`,
    `- 最终规则结论：**${view.verdictLabel}**`,
    `- 证据强度：${view.evidenceStrengthLabel}`,
    `- 可核验状态：${view.checkabilityLabel}`,
    `- 专业领域：${view.domainLabel}`,
    `- 采用证据：${view.acceptedEvidence.length} 条`,
    `- 排除证据：${view.excludedEvidence.length} 条`,
    `- 实质子主张：${view.materialSubclaimCount} 条`,
    `- 运行时间：${lineValue(metadata.createdAt, "未知")}`,
    `- 线程 ID：${lineValue(metadata.threadId, "未知")}`,
    `- 报告版本：${report.schema_version}`,
    "",
  ];

  if (view.subclaimRows.length) {
    lines.push(
      "## 子主张结果",
      "",
      "| 子主张 | LoRA 风险标签 | 规则结果 | 一致性 | 有效证据 | 分类耗时 |",
      "| --- | --- | --- | --- | ---: | ---: |",
      ...view.subclaimRows.map(
        (row) =>
          `| ${row.text.replaceAll("|", "\\|")} | ${row.modelLabel} | ${row.ruleDecision} | ${row.consistencyLabel} | ${row.evidenceCount} | ${row.latencyMs == null ? "—" : `${row.latencyMs} ms`} |`,
      ),
      "",
      "> LoRA 只读取子主张文本，没有读取本轮网页证据，其标签仅作为辅助信号。",
      "",
    );
  }

  lines.push("## 采用证据", "");
  if (!view.acceptedEvidence.length) {
    lines.push("- 本轮没有达到规则门槛的证据。", "");
  } else {
    for (const evidence of view.acceptedEvidence) {
      const url = safePublicHttpUrl(evidence.url);
      const title = url
        ? `[${lineValue(evidence.title)}](${url})`
        : lineValue(evidence.title);
      lines.push(
        `### ${title}`,
        "",
        `- 发布主体：${lineValue(evidence.publisher)}`,
        `- 立场：${lineValue(evidence.stance)}`,
        `- 来源等级：声明 ${evidence.claimed_source_level ?? evidence.source_level} / 代码校正 ${evidence.verified_source_level ?? evidence.source_level}`,
        `- 等级原因：${lineValue(evidence.source_grade_reason)}`,
        `- 证据形式：${lineValue(evidence.directness)}`,
        `- 发布时间：${lineValue(evidence.published_at ?? undefined, "未知")}`,
        `- 时效性：${lineValue(evidence.temporal_relevance)}`,
        `- 独立来源组：${lineValue(evidence.independent_group)}`,
        `- 关联子主张：${evidence.claim_ids?.length ? evidence.claim_ids.join("、") : "未标注"}`,
        `- 摘要：${lineValue(evidence.summary)}`,
        "",
      );
    }
  }

  lines.push("## 排除证据及原因", "");
  if (!view.excludedEvidence.length) {
    lines.push("- 无。", "");
  } else {
    for (const item of view.excludedEvidence) {
      const evidenceTitle = item.evidence?.title ?? item.evidenceId;
      lines.push(
        `- ${lineValue(evidenceTitle)}：${lineValue(item.explanation)}（${lineValue(item.reasonCode)}）`,
      );
    }
    lines.push("");
  }

  lines.push("## 传播时间线", "");
  if (!view.timelineEvents.length) {
    lines.push(
      "- 可追溯日期节点少于三个，时间线证据不足，未生成传播演化节点。",
      "",
    );
  } else {
    lines.push(
      "> 最早节点仅表示“本轮最早检索记录”，不代表互联网中的绝对首发。",
      "",
    );
    for (const event of view.timelineEvents) {
      const url = safePublicHttpUrl(event.url);
      const title = url
        ? `[${lineValue(event.title)}](${url})`
        : lineValue(event.title);
      lines.push(
        `- ${lineValue(event.date)} · ${lineValue(event.event_type)} · ${title} · ${event.used_for_decision ? "用于裁决" : "仅作传播记录"}`,
      );
    }
    lines.push("");
  }

  lines.push("## RAG 与 LoRA 辅助信号", "");
  const ragMatches = report.rag?.matches ?? [];
  lines.push(
    `- 历史谣言 RAG：${ragMatches.length ? `召回 ${ragMatches.length} 条历史相似记录` : "无命中或不可用"}。RAG 命中不等于当前主张为假。`,
    `- LoRA 分类：${lineValue(report.classifier_signal?.status, "不可用")}；聚合标签：${lineValue(report.classifier_signal?.aggregate_label ?? report.classifier_signal?.label, "未知")}。`,
    "",
  );

  const degradationCodes = metadata.degradationCodes ?? [];
  lines.push("## 能力降级与限制", "");
  const limitations = [...(report.limitations ?? [])];
  if (degradationCodes.length) {
    limitations.push(`降级代码：${degradationCodes.join("、")}`);
  }
  if (!limitations.length) {
    lines.push("- 本报告未记录额外限制。", "");
  } else {
    lines.push(...limitations.map((item) => `- ${redactPublicText(item)}`), "");
  }

  lines.push(
    "## 方法说明",
    "",
    "RumorBuster 将历史相似记录、实时网页研究和可选 LoRA 文本分类并行收集，在汇合后校验 URL、来源等级、职权、时效和独立性，再由确定性规则完成裁决。文本风险、RAG 与模型标签都不是事实证据。",
    "",
    `*导出时间：${metadata.exportedAt ?? new Date().toISOString()}*`,
  );

  return lines.join("\n").trimEnd() + "\n";
}

export function formatThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
): string {
  const report = thread.values?.rumor_report;
  if (report) {
    return formatRumorReportAsMarkdown(report, {
      title: titleOfThread(thread),
      threadId: thread.thread_id,
      createdAt: thread.created_at,
      exportedAt: new Date().toISOString(),
      degradationCodes: thread.values?.rumor_workflow?.degradation_codes,
    });
  }

  const lines = [
    `# ${titleOfThread(thread)}`,
    "",
    "> 当前会话尚未生成结构化核验报告，以下仅导出公开对话内容。",
    "",
  ];
  for (const item of publicConversation(messages)) {
    lines.push(
      item.role === "user" ? "## 用户" : "## 助手",
      "",
      item.content,
      "",
    );
  }
  return lines.join("\n").trimEnd() + "\n";
}

export function formatThreadAsJSON(
  thread: AgentThread,
  messages: Message[],
): string {
  const exportData = {
    export_kind: "rumorbuster-public-report-v1",
    title: titleOfThread(thread),
    thread_id: thread.thread_id,
    created_at: thread.created_at,
    exported_at: new Date().toISOString(),
    rumor_report: sanitizePublicValue(thread.values?.rumor_report ?? null),
    rumor_workflow: sanitizePublicValue(
      publicWorkflow(thread.values?.rumor_workflow ?? null),
    ),
    messages: publicConversation(messages),
  };
  return JSON.stringify(exportData, null, 2);
}

function publicWorkflow(workflow: RumorWorkflow | null): RumorWorkflow | null {
  if (!workflow) return null;
  return {
    input_message_id: workflow.input_message_id,
    run_id: workflow.run_id,
    stage: workflow.stage,
    degradation_codes: workflow.degradation_codes,
    branch_status: workflow.branch_status,
    trace: workflow.trace,
  };
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^\p{L}\p{N}_\- ]/gu, "").trim() || "rumorbuster-report";
}

export function downloadAsFile(
  content: string,
  filename: string,
  mimeType: string,
) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function exportThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
) {
  downloadAsFile(
    formatThreadAsMarkdown(thread, messages),
    `${sanitizeFilename(titleOfThread(thread))}.md`,
    "text/markdown;charset=utf-8",
  );
}

export function exportThreadAsJSON(thread: AgentThread, messages: Message[]) {
  downloadAsFile(
    formatThreadAsJSON(thread, messages),
    `${sanitizeFilename(titleOfThread(thread))}.json`,
    "application/json;charset=utf-8",
  );
}
