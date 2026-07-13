import test from "node:test";
import assert from "node:assert/strict";

import { MAX_SELECTION_LENGTH, buildRumorBusterUrl } from "../link.js";

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
