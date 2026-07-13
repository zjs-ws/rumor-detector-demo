"""Deterministic evidence policy for RumorBuster URL reports.

The model prompt asks for traceable citations, but provenance and confidence
must not depend on prompt compliance alone. This middleware validates the final
URL report against tool messages from the current run.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import override
from urllib.parse import unquote, urlsplit, urlunsplit

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_PLAIN_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+")
_VERDICT_PATTERN = re.compile(r"(?m)^\*\*判定结论\*\*[：:].*$")
_STRENGTH_PATTERN = re.compile(r"(?m)^\*\*证据强度\*\*[：:].*$")
_POLICY_NOTE = (
    "> **证据策略校正**：本轮仅成功读取待核验原网页，最终报告未引用任何由独立检索返回的外部来源，"
    "因此不能据此确认内容真伪。"
)


@dataclass(frozen=True)
class _FetchedPage:
    url: str
    title: str


def _normalize_url(value: str) -> str:
    """Normalize equivalent display encodings for provenance comparison."""
    parsed = urlsplit(value.rstrip(".,;:!?，。；：！？"))
    path = unquote(parsed.path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content) if content else ""


def _tool_name(message: object) -> str:
    name = getattr(message, "name", None)
    if isinstance(name, str):
        return name
    return ""


def _extract_urls(text: str) -> set[str]:
    return {
        normalized
        for raw_url in _PLAIN_URL_PATTERN.findall(text)
        if (normalized := _normalize_url(raw_url))
    }


def _parse_fetched_page(content: str) -> _FetchedPage | None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_url = payload.get("source_url") or payload.get("requested_url")
    if not isinstance(raw_url, str) or not raw_url.startswith(("http://", "https://")):
        return None
    raw_title = payload.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    return _FetchedPage(url=raw_url, title=title or "待核验原网页")


class RumorEvidencePolicyMiddleware(AgentMiddleware[AgentState]):
    """Enforce URL provenance and conservative verdicts on final reports."""

    def _apply(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_message = messages[-1]
        if getattr(last_message, "type", None) != "ai":
            return None
        if getattr(last_message, "tool_calls", None):
            return None

        content = _message_text(last_message)
        if "## 谣言检测报告" not in content:
            return None

        fetched_pages: list[_FetchedPage] = []
        search_urls: set[str] = set()
        for message in messages[:-1]:
            if getattr(message, "type", None) != "tool":
                continue
            tool_name = _tool_name(message)
            tool_content = _message_text(message)
            if tool_name == "web_fetch":
                page = _parse_fetched_page(tool_content)
                if page is not None:
                    fetched_pages.append(page)
            elif tool_name == "task":
                search_urls.update(_extract_urls(tool_content))

        if not fetched_pages:
            return None

        original_urls = {_normalize_url(page.url) for page in fetched_pages}
        independent_urls = search_urls - original_urls
        allowed_urls = original_urls | search_urls
        changed = False

        def remove_untraceable_link(match: re.Match[str]) -> str:
            nonlocal changed
            label, url = match.groups()
            if _normalize_url(url) in allowed_urls:
                return match.group(0)
            changed = True
            logger.warning("Removed untraceable URL from rumor report: %s", url)
            return f"{label}（未验证链接已移除）"

        corrected = _MARKDOWN_LINK_PATTERN.sub(remove_untraceable_link, content)

        cited_urls = {
            _normalize_url(url)
            for _, url in _MARKDOWN_LINK_PATTERN.findall(corrected)
        }
        cited_independent_urls = cited_urls & independent_urls

        # The original page must remain visible as the primary, explicitly
        # non-independent source even if the model omitted it.
        missing_pages = [
            page for page in fetched_pages if _normalize_url(page.url) not in cited_urls
        ]
        if missing_pages:
            if "### 来源" not in corrected:
                corrected = corrected.rstrip() + "\n\n### 来源\n"
            for page in missing_pages:
                corrected = (
                    corrected.rstrip()
                    + f"\n- [{page.title}]({page.url}) — 待核验原网页（非独立证据）\n"
                )
            changed = True

        if not cited_independent_urls:
            downgraded_verdict = "**判定结论**：存疑（证据不足，未获得独立外部来源）"
            downgraded_strength = "**证据强度**：低"

            if _VERDICT_PATTERN.search(corrected):
                corrected = _VERDICT_PATTERN.sub(downgraded_verdict, corrected)
            else:
                corrected = corrected.replace(
                    "## 谣言检测报告",
                    f"## 谣言检测报告\n\n{downgraded_verdict}",
                    1,
                )

            if _STRENGTH_PATTERN.search(corrected):
                corrected = _STRENGTH_PATTERN.sub(downgraded_strength, corrected)
            else:
                corrected = corrected.replace(
                    downgraded_verdict,
                    f"{downgraded_verdict}\n{downgraded_strength}",
                    1,
                )

            if _POLICY_NOTE not in corrected:
                corrected = corrected.replace(
                    downgraded_strength,
                    f"{downgraded_strength}\n\n{_POLICY_NOTE}",
                    1,
                )
            changed = True
            logger.info(
                "Downgraded URL fact-check report without cited independent evidence"
            )

        if not changed or corrected == content:
            return None
        return {"messages": [last_message.model_copy(update={"content": corrected})]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)
