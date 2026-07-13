import ipaddress
import json
import os
import re
import socket
from urllib.parse import urljoin, urlsplit

import requests
from langchain.tools import tool

from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

readability_extractor = ReadabilityExtractor()

_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3
_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


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


def _fetch_public_html(url: str, timeout: int) -> tuple[str, str] | str:
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
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; RumorBuster/0.1; "
                        "+https://github.com/zjs-ws/rumor-detector-demo)"
                    )
                },
                stream=True,
                timeout=(5, max(timeout, 5)),
            )
        except requests.RequestException as exc:
            return f"Error: Direct webpage fetch failed: {exc}"

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                return "Error: Webpage redirect did not include a destination"
            current_url = urljoin(current_url, location)
            continue

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

        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace"), current_url

    return f"Error: Webpage exceeded the {_MAX_REDIRECTS}-redirect limit"


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
) -> str:
    """Preserve source metadata together with bounded extracted content."""
    normalized_content = content.strip()
    bounded_content = normalized_content[:max_chars]
    return json.dumps(
        {
            "source_url": url,
            "requested_url": requested_url or url,
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
    max_chars = int(extra.get("max_chars") or 2048)

    if os.getenv("JINA_API_KEY", "").strip():
        jina_client = JinaClient()
        text = jina_client.crawl(url, return_format="markdown", timeout=timeout)
        if not text.startswith("Error:") and text.strip():
            return _build_structured_result(url, text, max_chars)

    local_result = _fetch_public_html(url, timeout)
    if isinstance(local_result, str):
        return local_result

    html_content, resolved_url = local_result
    article = readability_extractor.extract_article(html_content)
    return _build_structured_result(
        resolved_url,
        article.to_markdown(),
        max_chars,
        requested_url=url,
    )
