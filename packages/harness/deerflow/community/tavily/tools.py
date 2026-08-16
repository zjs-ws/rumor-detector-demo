import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit

from langchain.tools import tool
from tavily import TavilyClient

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

# Tavily API: ultra-fast minimizes latency; advanced is slower (2 credits). See:
# https://docs.tavily.com/documentation/api-reference/endpoint/search
_DEFAULT_SEARCH_DEPTH = "ultra-fast"
_DEFAULT_INCLUDE_ANSWER = False
_DEFAULT_INCLUDE_IMAGES = False


def _tool_extra(config) -> dict:
    """Extra fields from ToolConfig (Pydantic v2 may use __pydantic_extra__ or model_extra)."""
    if config is None:
        return {}
    ex = getattr(config, "__pydantic_extra__", None)
    if isinstance(ex, dict) and ex:
        return ex
    ex = getattr(config, "model_extra", None)
    if isinstance(ex, dict) and ex:
        return ex
    return {}


def _get_tavily_client() -> TavilyClient:
    config = get_app_config().get_tool_config("web_search")
    extra = _tool_extra(config)
    api_key = extra.get("api_key")
    return TavilyClient(api_key=api_key)


def _search_params_from_config(config) -> dict:
    """Build Tavily search kwargs from tool config (model_extra)."""
    extra = _tool_extra(config)
    depth = extra.get("search_depth", _DEFAULT_SEARCH_DEPTH)
    include_answer = extra.get("include_answer", _DEFAULT_INCLUDE_ANSWER)
    include_images = extra.get("include_images", _DEFAULT_INCLUDE_IMAGES)
    return {
        "search_depth": depth,
        "include_answer": include_answer,
        "include_images": include_images,
    }


@tool("web_search", parse_docstring=True)
def web_search_tool(query: str) -> str:
    """Search the web.

    Args:
        query: The query to search for.
    """
    config = get_app_config().get_tool_config("web_search")
    extra = _tool_extra(config)
    max_results = int(extra.get("max_results") or 5)

    client = _get_tavily_client()
    search_kwargs = _search_params_from_config(config)
    search_kwargs["max_results"] = max_results

    try:
        res = client.search(query, **search_kwargs)
    except Exception as exc:
        # Older SDKs or API quirks: fall back to basic depth once
        if search_kwargs.get("search_depth") not in (None, "basic"):
            logger.warning("Tavily search with depth=%s failed (%s); retrying with basic", search_kwargs.get("search_depth"), exc)
            search_kwargs["search_depth"] = "basic"
            res = client.search(query, **search_kwargs)
        else:
            raise
    normalized_results = [
        {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "snippet": result.get("content", ""),
        }
        for result in res.get("results", [])
    ]
    # Compact JSON — less token overhead for the model
    return json.dumps({"query": query, "results": normalized_results}, ensure_ascii=False)


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
    client = _get_tavily_client()
    res = client.extract([url])
    if "failed_results" in res and len(res["failed_results"]) > 0:
        return f"Error: {res['failed_results'][0]['error']}"
    elif "results" in res and len(res["results"]) > 0:
        result = res["results"][0]
        return _build_structured_result(
            str(result.get("url") or url),
            str(result.get("raw_content") or ""),
            requested_url=url,
        )
    else:
        return "Error: No results found"


def _build_structured_result(
    url: str,
    content: str,
    *,
    requested_url: str | None = None,
) -> str:
    """Preserve source metadata together with bounded extracted content.

    The field contract mirrors ``jina_ai.tools._build_structured_result`` so
    graph_v3 provenance binding works with any configured provider.
    """
    config = get_app_config().get_tool_config("web_fetch")
    extra = _tool_extra(config)
    max_chars = int(extra.get("max_chars") or 12000)
    normalized_content = content.strip()
    bounded_content = normalized_content[:max_chars]
    return json.dumps(
        {
            "source_url": url,
            "requested_url": requested_url or url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "title": str(urlsplit(url).hostname or "Untitled"),
            "content": bounded_content,
            "content_chars": len(bounded_content),
            "original_content_chars": len(normalized_content),
            "truncated": len(normalized_content) > max_chars,
        },
        ensure_ascii=False,
    )
