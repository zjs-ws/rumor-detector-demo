import type { Message } from "@langchain/langgraph-sdk";

const SENSITIVE_KEY_PATTERN =
  /authorization|api[_-]?key|secret|token|password|service[_-]?(url|address)|base[_-]?url/i;
const INLINE_SECRET_PATTERNS = [
  /\bBearer\s+[A-Za-z0-9._~+/=-]+/gi,
  /\bsk-[A-Za-z0-9_-]{12,}\b/g,
  /\b(api[_-]?key|authorization|secret|password)\s*[:=]\s*[^\s,;]+/gi,
];
const INLINE_REASONING_PATTERN = /<think>\s*[\s\S]*?\s*<\/think>/gi;
const UPLOADED_FILES_PATTERN = /<uploaded_files>[\s\S]*?<\/uploaded_files>/gi;

export function redactPublicText(value: string): string {
  const withoutPrivateBlocks = value
    .replace(INLINE_REASONING_PATTERN, "")
    .replace(UPLOADED_FILES_PATTERN, "");
  return INLINE_SECRET_PATTERNS.reduce(
    (result, pattern) => result.replace(pattern, "[已脱敏]"),
    withoutPrivateBlocks,
  ).trim();
}

export function sanitizePublicValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizePublicValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).flatMap(([key, nested]) =>
        SENSITIVE_KEY_PATTERN.test(key)
          ? []
          : [[key, sanitizePublicValue(nested)]],
      ),
    );
  }
  return typeof value === "string" ? redactPublicText(value) : value;
}

function plainMessageText(message: Message): string {
  if (typeof message.content === "string") {
    return redactPublicText(message.content);
  }
  if (!Array.isArray(message.content)) return "";
  return redactPublicText(
    message.content
      .flatMap((part) => (part.type === "text" ? [part.text] : []))
      .join("\n"),
  );
}

export function publicConversation(messages: Message[]) {
  return messages.flatMap((message) => {
    if (message.type !== "human" && message.type !== "ai") return [];
    if (message.type === "ai" && message.tool_calls?.length) return [];
    const content = plainMessageText(message);
    if (!content) return [];
    return [{ role: message.type === "human" ? "user" : "assistant", content }];
  });
}
