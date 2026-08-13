import type { Message } from "@langchain/langgraph-sdk";

import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  hasContent,
  hasToolCalls,
  stripUploadedFilesTag,
} from "../messages/utils";

import type { AgentThread } from "./types";
import { titleOfThread } from "./utils";

function formatMessageContent(message: Message): string {
  const text = extractContentFromMessage(message);
  if (!text) return "";
  return stripUploadedFilesTag(text);
}

function formatToolCalls(message: Message): string {
  if (message.type !== "ai" || !hasToolCalls(message)) return "";
  const calls = message.tool_calls ?? [];
  return calls.map((call) => `- **Tool:** \`${call.name}\``).join("\n");
}

export function formatThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
): string {
  const title = titleOfThread(thread);
  const createdAt = thread.created_at
    ? new Date(thread.created_at).toLocaleString()
    : "Unknown";

  const lines: string[] = [
    `# ${title}`,
    "",
    `*Exported on ${new Date().toLocaleString()} · Created ${createdAt}*`,
    "",
    "---",
    "",
  ];

  for (const message of messages) {
    if (message.type === "human") {
      const content = formatMessageContent(message);
      if (content) {
        lines.push(`## 🧑 User`, "", content, "", "---", "");
      }
    } else if (message.type === "ai") {
      const reasoning = extractReasoningContentFromMessage(message);
      const content = formatMessageContent(message);
      const toolCalls = formatToolCalls(message);

      if (!content && !toolCalls && !reasoning) continue;

      lines.push(`## 🤖 Assistant`);

      if (reasoning) {
        lines.push(
          "",
          "<details>",
          "<summary>Thinking</summary>",
          "",
          reasoning,
          "",
          "</details>",
        );
      }

      if (toolCalls) {
        lines.push("", toolCalls);
      }

      if (content && hasContent(message)) {
        lines.push("", content);
      }

      lines.push("", "---", "");
    }
  }

  const report = thread.values?.rumor_report;
  if (report) {
    lines.push("# RumorBuster 结构化结果", "");
    lines.push(`- Schema：${report.schema_version}`);
    lines.push(`- 结论：${report.decision.verdict}`);
    lines.push(`- 证据强度：${report.decision.strength}`);
    if (report.claim?.normalized_claim) {
      lines.push(`- 标准化主张：${report.claim.normalized_claim}`);
    }
    if (report.domain_route) {
      lines.push(
        `- 领域路由：${report.domain_route.domain}（${report.domain_route.reason}）`,
      );
    }
    lines.push("");
    const risk = report.claim?.text_risk_analysis;
    if (risk?.status === "completed") {
      lines.push(
        "## 文本风险分析",
        "",
        "> 文本风险不等于事实为假；以下内容只用于形成核验目标。",
        "",
      );
      for (const signal of risk.signals.filter(
        (item) => item.level !== "none",
      )) {
        lines.push(
          `- ${signal.dimension}（${signal.level}）：${signal.spans.join("；") || signal.note || "未提供可追溯片段"}`,
        );
      }
      for (const target of risk.verification_targets) {
        lines.push(`- 核验目标 ${target.kind}：${target.text}`);
      }
      lines.push("");
    }
    if (report.classifier_signal) {
      lines.push(
        "## 微调模型信号与审计",
        "",
        `- 模型：${report.classifier_signal.model_id ?? "未配置"}`,
        `- API：${report.classifier_signal.api_style ?? "未配置"}`,
        `- 状态：${report.classifier_signal.status}`,
        `- 聚合标签：${report.classifier_signal.aggregate_label ?? report.classifier_signal.label}`,
        "- 说明：模型仅根据文本模式输出风险标签，没有读取本轮网页证据。",
        "",
      );
      for (const item of report.classifier_signal.subclaims ?? []) {
        const verdict =
          report.decision.subclaim_decisions?.[item.claim_id] ?? "不可比较";
        const consistency =
          report.decision.classifier_consistency_by_claim?.[item.claim_id] ??
          "not_comparable";
        lines.push(
          `- ${item.claim_id}：LoRA=${item.mapped_label}，规则=${verdict}，一致性=${consistency}，耗时=${item.latency_ms ?? 0} ms`,
        );
      }
      lines.push("");
    }
    if (report.research_branches) {
      lines.push("## 并行核验分支", "");
      for (const [name, branch] of Object.entries(report.research_branches)) {
        lines.push(
          `- ${name}：${branch.status}${branch.duration_ms != null ? `，${branch.duration_ms} ms` : ""}${branch.result_count != null ? `，${branch.result_count} 条结果` : ""}`,
        );
      }
      lines.push("");
    }
    if (report.evidence_review) {
      lines.push("## 证据审查", "", report.evidence_review.notes, "");
    }
    if (report.timeline?.timeline_status === "ready") {
      lines.push("## 传播演化时间线", "");
      for (const event of report.timeline.events) {
        lines.push(
          `- ${event.date} · ${event.event_type} · [${event.title}](${event.url}) · ${event.used_for_decision ? "用于裁决" : "仅作传播记录"}`,
        );
      }
      lines.push("", report.timeline.note, "");
    }
  }

  return lines.join("\n").trimEnd() + "\n";
}

export function formatThreadAsJSON(
  thread: AgentThread,
  messages: Message[],
): string {
  const exportData = {
    title: titleOfThread(thread),
    thread_id: thread.thread_id,
    created_at: thread.created_at,
    exported_at: new Date().toISOString(),
    rumor_report: thread.values?.rumor_report ?? null,
    rumor_workflow: thread.values?.rumor_workflow ?? null,
    messages: messages.map((msg) => ({
      type: msg.type,
      id: msg.id,
      content: typeof msg.content === "string" ? msg.content : msg.content,
      ...(msg.type === "ai" && msg.tool_calls?.length
        ? { tool_calls: msg.tool_calls }
        : {}),
    })),
  };
  return JSON.stringify(exportData, null, 2);
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^\p{L}\p{N}_\- ]/gu, "").trim() || "conversation";
}

export function downloadAsFile(
  content: string,
  filename: string,
  mimeType: string,
) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function exportThreadAsMarkdown(
  thread: AgentThread,
  messages: Message[],
) {
  const markdown = formatThreadAsMarkdown(thread, messages);
  const filename = `${sanitizeFilename(titleOfThread(thread))}.md`;
  downloadAsFile(markdown, filename, "text/markdown;charset=utf-8");
}

export function exportThreadAsJSON(thread: AgentThread, messages: Message[]) {
  const json = formatThreadAsJSON(thread, messages);
  const filename = `${sanitizeFilename(titleOfThread(thread))}.json`;
  downloadAsFile(json, filename, "application/json;charset=utf-8");
}
