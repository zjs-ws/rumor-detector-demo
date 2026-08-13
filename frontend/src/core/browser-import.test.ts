import assert from "node:assert/strict";
import test from "node:test";

const { formatBrowserClaimPrompt, parseBrowserClaimFragment } = await import(
  new URL("./browser-import.ts", import.meta.url).href
);

void test("imports claim and public source from a URL fragment", () => {
  const result = parseBrowserClaimFragment(
    "#claim=%E7%BD%91%E4%BC%A0%E8%AF%B4%E6%B3%95&source=https%3A%2F%2Fexample.com%2Fnews",
  );

  assert.deepEqual(result, {
    claim: "网传说法",
    source: "https://example.com/news",
    truncated: false,
  });
  assert.ok(result);
  assert.match(
    formatBrowserClaimPrompt(result),
    /来源页面：https:\/\/example\.com\/news/,
  );
});

void test("drops unsafe source protocols and preserves truncation status", () => {
  const result = parseBrowserClaimFragment(
    `#claim=${encodeURIComponent("谣".repeat(2100))}&source=${encodeURIComponent("javascript:alert(1)")}`,
  );

  assert.equal(result?.claim.length, 2000);
  assert.equal(result?.source, null);
  assert.equal(result?.truncated, true);
});
