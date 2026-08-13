import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_RUMOR_BUSTER_BASE_URL,
  MAX_SELECTION_LENGTH,
  buildRumorBusterUrl,
  normalizeRumorBusterBaseUrl,
} from "../link.js";

test("returns null when no text is selected", () => {
  assert.equal(buildRumorBusterUrl("   ", "https://example.com"), null);
});

test("puts claim and source in the fragment instead of the request query", () => {
  const result = buildRumorBusterUrl(
    "  网传这是一条未经证实的消息  ",
    "https://example.com/news?id=7",
  );
  const url = new URL(result);
  const fragment = new URLSearchParams(url.hash.slice(1));

  assert.equal(url.pathname, "/workspace/chats/new");
  assert.equal(url.search, "");
  assert.equal(fragment.get("claim"), "网传这是一条未经证实的消息");
  assert.equal(fragment.get("source"), "https://example.com/news?id=7");
});

test("limits oversized selections and marks them as truncated", () => {
  const result = buildRumorBusterUrl("谣".repeat(MAX_SELECTION_LENGTH + 10));
  const url = new URL(result);
  const fragment = new URLSearchParams(url.hash.slice(1));

  assert.equal(fragment.get("claim").length, MAX_SELECTION_LENGTH);
  assert.equal(fragment.get("truncated"), "1");
});

test("drops non-web source URLs", () => {
  const result = buildRumorBusterUrl("待核验内容", "chrome://extensions");
  const url = new URL(result);
  const fragment = new URLSearchParams(url.hash.slice(1));

  assert.equal(fragment.get("source"), null);
});

test("uses the production compose port by default", () => {
  assert.equal(DEFAULT_RUMOR_BUSTER_BASE_URL, "http://localhost:8080");
  const result = buildRumorBusterUrl("待核验内容");
  assert.equal(new URL(result).origin, "http://localhost:8080");
});

test("accepts a configured HTTP(S) base URL and removes extra paths", () => {
  assert.equal(
    normalizeRumorBusterBaseUrl("https://rumor.example.org/custom/path"),
    "https://rumor.example.org",
  );
  assert.equal(
    new URL(
      buildRumorBusterUrl(
        "待核验内容",
        "https://source.example.org/news",
        "https://rumor.example.org/custom/path",
      ),
    ).origin,
    "https://rumor.example.org",
  );
});

test("rejects non-web base URLs", () => {
  assert.equal(normalizeRumorBusterBaseUrl("file:///tmp/app"), null);
  assert.equal(
    buildRumorBusterUrl("待核验内容", "", "javascript:alert(1)"),
    null,
  );
});
