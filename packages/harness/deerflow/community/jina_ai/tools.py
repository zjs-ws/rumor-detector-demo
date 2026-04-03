from langchain.tools import tool

from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.config import get_app_config
from deerflow.utils.readability import ReadabilityExtractor

readability_extractor = ReadabilityExtractor()


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
    config = get_app_config().get_tool_config("web_fetch")
    extra = _tool_extra(config)
    timeout = int(extra.get("timeout") or 10)
    max_chars = int(extra.get("max_chars") or 2048)

    jina_client = JinaClient()
    # Fast path: Jina Reader markdown — skips local HTML + Readability/readabilipy (often slow).
    text = jina_client.crawl(url, return_format="markdown", timeout=timeout)
    if not text.startswith("Error:") and text.strip():
        return text.strip()[:max_chars]

    # Fallback: HTML + extract main article (slower; some pages parse poorly as markdown-only).
    html_content = jina_client.crawl(url, return_format="html", timeout=timeout)
    if html_content.startswith("Error:"):
        return html_content
    article = readability_extractor.extract_article(html_content)
    return article.to_markdown()[:max_chars]
