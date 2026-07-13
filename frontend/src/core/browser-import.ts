const MAX_IMPORTED_CLAIM_LENGTH = 2000;

export type BrowserClaimImport = {
  claim: string;
  source: string | null;
  truncated: boolean;
};

function normalizeSourceUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function parseBrowserClaimFragment(
  fragment: string,
): BrowserClaimImport | null {
  const value = fragment.startsWith("#") ? fragment.slice(1) : fragment;
  const params = new URLSearchParams(value);
  const claim = params.get("claim")?.trim();

  if (!claim) {
    return null;
  }

  return {
    claim: claim.slice(0, MAX_IMPORTED_CLAIM_LENGTH),
    source: normalizeSourceUrl(params.get("source")),
    truncated:
      params.get("truncated") === "1" ||
      claim.length > MAX_IMPORTED_CLAIM_LENGTH,
  };
}

export function formatBrowserClaimPrompt(imported: BrowserClaimImport): string {
  const sections = ["请核验以下网页内容：", "", imported.claim];

  if (imported.truncated) {
    sections.push("", "（选中文字过长，当前仅保留前 2000 个字符。）");
  }
  if (imported.source) {
    sections.push("", `来源页面：${imported.source}`);
  }

  return sections.join("\n");
}
