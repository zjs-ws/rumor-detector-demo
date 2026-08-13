export const DEFAULT_RUMOR_BUSTER_BASE_URL = "http://localhost:8080";
export const RUMORBUSTER_BASE_URL = DEFAULT_RUMOR_BUSTER_BASE_URL;
export const MAX_SELECTION_LENGTH = 2000;

export function normalizeRumorBusterBaseUrl(value) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    url.hash = "";
    url.search = "";
    url.pathname = "/";
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function normalizeSourceUrl(sourceUrl) {
  if (!sourceUrl) {
    return null;
  }

  try {
    const url = new URL(sourceUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function buildRumorBusterUrl(
  selectionText,
  sourceUrl,
  baseUrl = RUMORBUSTER_BASE_URL,
) {
  const claim = selectionText?.trim();
  if (!claim) {
    return null;
  }

  const normalizedBaseUrl = normalizeRumorBusterBaseUrl(baseUrl);
  if (!normalizedBaseUrl) {
    return null;
  }

  const target = new URL("/workspace/chats/new", normalizedBaseUrl);
  const params = new URLSearchParams();
  const truncated = claim.length > MAX_SELECTION_LENGTH;

  params.set("claim", claim.slice(0, MAX_SELECTION_LENGTH));
  const normalizedSource = normalizeSourceUrl(sourceUrl);
  if (normalizedSource) {
    params.set("source", normalizedSource);
  }
  if (truncated) {
    params.set("truncated", "1");
  }

  // A fragment is not sent with the HTTP request, so selected text stays out
  // of the local web server's access logs.
  target.hash = params.toString();
  return target.toString();
}
