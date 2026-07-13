export const RUMORBUSTER_BASE_URL = "http://localhost:3000";
export const MAX_SELECTION_LENGTH = 2000;

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

  const target = new URL("/workspace/chats/new", baseUrl);
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
