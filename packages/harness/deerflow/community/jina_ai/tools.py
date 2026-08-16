import io
import ipaddress
import json
import logging
import os
import re
import socket
import time
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import requests
from langchain.tools import tool

from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

logger = logging.getLogger(__name__)

readability_extractor = ReadabilityExtractor()

_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_MAX_PDF_TEXT_CHARS = 500_000
_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/pdf")

# Browser-like headers substantially reduce anti-bot 403s on sites such as
# cdc.gov; the RumorBuster identity marker is deliberately dropped here.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Transient failures get up to two quick retries.  Deterministic rejections
# (403/404, unsupported content type) and read timeouts are not retried so
# the 55-second research budget is preserved.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.5, 1.0)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class _TransientFetchError(Exception):
    """Raised for network failures worth a quick retry."""


def _decode_web_content(raw: bytes, *declared_encodings: str | None) -> str:
    """Choose the least-corrupted decoding for frequently mislabeled Chinese pages."""
    encodings: list[str] = []
    for value in (*declared_encodings, "utf-8", "gb18030"):
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in {item.lower() for item in encodings}:
            encodings.append(normalized)

    candidates: list[str] = []
    for encoding in encodings:
        try:
            candidates.append(raw.decode(encoding))
        except (LookupError, UnicodeDecodeError):
            continue
    if not candidates:
        return raw.decode("utf-8", errors="replace")

    def score(text: str) -> tuple[int, int]:
        cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
        corruption = text.count("�") * 20 + sum(text.count(token) for token in ("Ã", "Â", "å", "æ", "½"))
        return cjk - corruption, -corruption

    return max(candidates, key=score)


def _normalize_published_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    match = re.search(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?", text)
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        ).date()
    except ValueError:
        return None
    if parsed > datetime.now(UTC).date():
        return None
    return parsed.isoformat()


def _extract_published_at(content: str) -> str | None:
    """Extract conservative publication metadata before considering visible text."""
    head = content[:12000]
    metadata_patterns = (
        r"(?is)(?:article:published_time|datePublished|datepublished)[^>]{0,160}?(?:content=|:\s*)[\"']([^\"']+)",
        r"(?is)(?:content=)[\"']([^\"']+)[\"'][^>]{0,160}?(?:article:published_time|datePublished|datepublished)",
        r"(?is)<time[^>]+datetime=[\"']([^\"']+)",
        r"(?im)^(?:Published Time|Publication Date|发布日期|发布时间)\s*[:：]\s*(.+)$",
    )
    for pattern in metadata_patterns:
        match = re.search(pattern, head)
        normalized = _normalize_published_date(match.group(1) if match else None)
        if normalized:
            return normalized

    # Many Chinese news pages expose the publication time as visible text near
    # the title but omit machine-readable metadata. Limit this fallback to the
    # beginning of the extracted article so dates in the body are not mistaken
    # for the page's own publication date.
    return _normalize_published_date(head[:1500])


def _validate_public_http_url(url: str) -> str | None:
    """Return an error for URLs that are not safe public web targets."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "URL is invalid"

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "Only public HTTP(S) URLs are supported"

    hostname = parsed.hostname.rstrip(".").lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal"))
        or hostname.isdigit()
    ):
        return "Only public HTTP(S) URLs are supported"

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return None

    if not address.is_global:
        return "Only public HTTP(S) URLs are supported"
    return None


def _validate_public_dns_target(url: str) -> str | None:
    """Reject hostnames that resolve to loopback, private, or reserved IPs."""
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    try:
        addresses = {
            ipaddress.ip_address(sockaddr[0])
            for *_prefix, sockaddr in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, ValueError) as exc:
        return f"Could not resolve URL hostname: {exc}"

    if not addresses or any(not address.is_global for address in addresses):
        return "Only public HTTP(S) URLs are supported"
    return None


def _fetch_public_html(url: str, timeout: int) -> tuple[str, str, bool] | str:
    """Fetch bounded public HTML, retrying transient network failures."""
    last_error = ""
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
        try:
            return _fetch_public_html_once(url, timeout)
        except _TransientFetchError as exc:
            last_error = str(exc)
    return f"Error: Direct webpage fetch failed after {_MAX_ATTEMPTS} attempts: {last_error}"


def _fetch_public_html_once(url: str, timeout: int) -> tuple[str, str, bool] | str:
    """Fetch bounded public HTML while validating every redirect target."""
    current_url = url
    for _redirect_count in range(_MAX_REDIRECTS + 1):
        validation_error = _validate_public_http_url(current_url)
        if validation_error is None:
            validation_error = _validate_public_dns_target(current_url)
        if validation_error is not None:
            return f"Error: {validation_error}"

        try:
            response = requests.get(
                current_url,
                allow_redirects=False,
                headers=_BROWSER_HEADERS,
                stream=True,
                timeout=(5, max(timeout, 5)),
            )
        except (requests.ConnectionError, requests.ConnectTimeout) as exc:
            raise _TransientFetchError(str(exc)) from exc
        except requests.RequestException as exc:
            # Read timeouts and TLS handshake failures are not retried.
            return f"Error: Direct webpage fetch failed: {exc}"

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                return "Error: Webpage redirect did not include a destination"
            current_url = urljoin(current_url, location)
            continue

        if response.status_code in _RETRYABLE_STATUS_CODES:
            response.close()
            raise _TransientFetchError(f"HTTP {response.status_code}")

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            response.close()
            return f"Error: Direct webpage fetch failed: {exc}"

        content_type = response.headers.get("content-type", "").lower()
        if content_type and not content_type.startswith(_ALLOWED_CONTENT_TYPES):
            response.close()
            return f"Error: Unsupported webpage content type: {content_type}"

        chunks: list[bytes] = []
        downloaded = 0
        response_encoding = response.encoding
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > _MAX_DOWNLOAD_BYTES:
                    return "Error: Webpage exceeds the 2 MiB download limit"
                chunks.append(chunk)
        finally:
            response.close()

        raw_content = b"".join(chunks)
        if content_type.startswith("application/pdf"):
            return _extract_pdf_text(raw_content), current_url, True
        header_encoding = requests.utils.get_encoding_from_headers(response.headers)
        detected_encoding: str | None = None
        if not header_encoding and (not response_encoding or response_encoding.lower() in {"iso-8859-1", "latin-1"}):
            try:
                from charset_normalizer import from_bytes

                best = from_bytes(raw_content).best()
                detected_encoding = best.encoding if best is not None else None
            except Exception:
                detected_encoding = None
        return _decode_web_content(raw_content, header_encoding, response_encoding, detected_encoding), current_url, False

    return f"Error: Webpage exceeded the {_MAX_REDIRECTS}-redirect limit"


def _extract_pdf_text(raw: bytes) -> str:
    """Extract bounded text from a downloaded PDF; empty on any failure."""
    try:
        from pypdf import PdfReader

        pages: list[str] = []
        total = 0
        for page in PdfReader(io.BytesIO(raw)).pages:
            text = page.extract_text() or ""
            pages.append(text)
            total += len(text)
            if total > _MAX_PDF_TEXT_CHARS:
                break
        return "\n".join(pages)[:_MAX_PDF_TEXT_CHARS]
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def _extract_title(content: str, url: str) -> str:
    """Extract a useful citation title from Jina Reader markdown."""
    for pattern in (r"(?mi)^Title:\s*(.+?)\s*$", r"(?m)^#\s+(.+?)\s*$"):
        match = re.search(pattern, content)
        if match is not None:
            return match.group(1).strip()
    return urlsplit(url).hostname or "Untitled"


def _build_structured_result(
    url: str,
    content: str,
    max_chars: int,
    *,
    requested_url: str | None = None,
    published_at: str | None = None,
) -> str:
    """Preserve source metadata together with bounded extracted content."""
    normalized_content = content.strip()
    bounded_content = normalized_content[:max_chars]
    return json.dumps(
        {
            "source_url": url,
            "requested_url": requested_url or url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "published_at": published_at or _extract_published_at(normalized_content),
            "title": _extract_title(normalized_content, url),
            "content": bounded_content,
            "content_chars": len(bounded_content),
            "original_content_chars": len(normalized_content),
            "truncated": len(normalized_content) > max_chars,
        },
        ensure_ascii=False,
    )


def _tool_extra(config) -> dict:
    if config is None:
        return {}
    ex = getattr(config, "__pydantic_extra__", None)
    if isinstance(ex, dict) and ex:
        return ex
    ex = getattr(config, "model_extra", None)
    if isinstance(ex, dict) and ex:
        return ex
    return {}


@tool("web_fetch", parse_docstring=True)
def web_fetch_tool(url: str) -> str:
    """Fetch the contents of a web page at a given URL.
    Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
    This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
    Do NOT add www. to URLs that do NOT have them.
    URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

    Args:
        url: The URL to fetch the contents of.
    """
    validation_error = _validate_public_http_url(url)
    if validation_error is not None:
        return f"Error: {validation_error}"

    config = get_app_config().get_tool_config("web_fetch")
    extra = _tool_extra(config)
    timeout = int(extra.get("timeout") or 10)
    max_chars = int(extra.get("max_chars") or 12000)

    # Jina Reader requires an API key (keyless requests are rejected), so it
    # is only attempted when JINA_API_KEY is configured.
    if os.getenv("JINA_API_KEY", "").strip():
        jina_client = JinaClient()
        text = jina_client.crawl(url, return_format="markdown", timeout=timeout)
        if not text.startswith("Error:") and text.strip():
            return _build_structured_result(
                url,
                text,
                max_chars,
                published_at=_extract_published_at(text),
            )
        logger.warning("Jina fetch failed, falling back to direct fetch: %s", text.split("\n")[0][:200])

    local_result = _fetch_public_html(url, timeout)
    if isinstance(local_result, str):
        return local_result

    content, resolved_url, is_pdf = local_result
    if is_pdf:
        markdown = content
        if not markdown.strip():
            # Report empty bodies as failures so the research model tries the
            # next candidate instead of treating a shell document as fetched.
            return "Error: PDF contains no extractable text content"
    else:
        article = readability_extractor.extract_article(content)
        markdown = article.to_markdown()
        if not markdown.strip():
            # Report empty bodies as failures so the research model tries the
            # next candidate instead of treating a shell page as fetched.
            return "Error: Webpage contains no readable text content"
    return _build_structured_result(
        resolved_url,
        markdown,
        max_chars,
        requested_url=url,
        published_at=_extract_published_at(markdown),
    )
