import assert from "node:assert/strict";
import test from "node:test";

import type { Message } from "@langchain/langgraph-sdk";

const { publicConversation, redactPublicText, sanitizePublicValue } =
  await import(new URL("./export-safety.ts", import.meta.url).href);

void test("public conversation excludes tool calls and inline reasoning", () => {
  const messages = [
    { type: "human", content: "请核验这条消息", id: "human-1" },
    {
      type: "ai",
      content: "<think>内部推理不得导出</think>公开回答",
      id: "ai-1",
    },
    {
      type: "ai",
      content: "准备调用内部工具",
      id: "ai-2",
      tool_calls: [{ name: "web_search", args: { query: "私有参数" } }],
    },
    { type: "tool", content: "原始工具结果", id: "tool-1" },
  ] as unknown as Message[];

  assert.deepEqual(publicConversation(messages), [
    { role: "user", content: "请核验这条消息" },
    { role: "assistant", content: "公开回答" },
  ]);
});

void test("public export redacts secrets and drops sensitive object keys", () => {
  const sanitized = sanitizePublicValue({
    verdict: "证据不足",
    authorization: "Bearer hidden-token",
    api_key: "example-secret-value",
    nested: {
      service_url: "http://internal-model:8000",
      explanation: "authorization=hidden-value 结论保持不变",
    },
  });

  assert.deepEqual(sanitized, {
    verdict: "证据不足",
    nested: { explanation: "[已脱敏] 结论保持不变" },
  });
  assert.equal(
    redactPublicText("Bearer abc.def.ghi 可公开内容"),
    "[已脱敏] 可公开内容",
  );
});
