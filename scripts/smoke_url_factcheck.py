#!/usr/bin/env python3
"""Run a real URL fact-check against the local LangGraph service."""

import argparse
import asyncio
import os
import re
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from langgraph_sdk import get_client

_MARKDOWN_URL_PATTERN = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_PLAIN_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+")


def _normalize_url(value: str) -> str:
    """Normalize equivalent display encodings before provenance comparison."""
    parsed = urlsplit(value.rstrip(".,;:!?"))
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


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return str(content)


async def run(base_url: str, target_url: str) -> None:
    client = get_client(url=base_url)
    assistants = await client.assistants.search(graph_id="rumor_agent")
    if not assistants:
        raise RuntimeError("rumor_agent assistant was not found")

    thread = await client.threads.create()
    result = await client.runs.wait(
        thread["thread_id"],
        assistants[0]["assistant_id"],
        input={
            "messages": [
                {
                    "role": "user",
                    "content": f"请读取并核验这个网页的主要内容：{target_url}",
                }
            ]
        },
        config={"recursion_limit": 100},
    )

    messages = result.get("messages", [])
    final_text = next(
        (
            _message_text(message)
            for message in reversed(messages)
            if message.get("type") in {"ai", "assistant"}
        ),
        "",
    )
    if not final_text:
        raise RuntimeError("rumor_agent returned no final assistant message")

    print(final_text)
    if target_url not in final_text:
        raise RuntimeError("report did not preserve the requested source URL")
    if "### 来源" not in final_text:
        raise RuntimeError("report did not include the Sources section")
    sources_section = final_text.split("### 来源", maxsplit=1)[1]
    if target_url not in sources_section:
        raise RuntimeError("Sources section did not include the fetched source page")
    citation_urls = set(_MARKDOWN_URL_PATTERN.findall(final_text))
    if not citation_urls:
        raise RuntimeError("report did not contain a clickable Markdown citation")

    tool_evidence = "\n".join(
        _message_text(message)
        for message in messages
        if message.get("type") == "tool"
    )
    traceable_urls = {
        _normalize_url(url)
        for url in {target_url, *_PLAIN_URL_PATTERN.findall(tool_evidence)}
    }
    untraceable_urls = {
        url for url in citation_urls if _normalize_url(url) not in traceable_urls
    }
    if untraceable_urls:
        raise RuntimeError(
            "report cited URLs absent from this run's evidence: "
            + ", ".join(sorted(untraceable_urls))
        )

    task_evidence = "\n".join(
        _message_text(message)
        for message in messages
        if message.get("type") == "tool" and message.get("name") == "task"
    )
    original_url = _normalize_url(target_url)
    independent_urls = {
        _normalize_url(url)
        for url in _PLAIN_URL_PATTERN.findall(task_evidence)
        if _normalize_url(url) != original_url
    }
    cited_independent_urls = {
        _normalize_url(url) for url in citation_urls
    } & independent_urls
    if not cited_independent_urls:
        if "**判定结论**：存疑（证据不足，未获得独立外部来源）" not in final_text:
            raise RuntimeError(
                "report lacked a cited independent source but was not downgraded"
            )
        if "**证据强度**：低" not in final_text:
            raise RuntimeError(
                "report lacked a cited independent source but evidence was not low"
            )

    print(f"\nTRACEABLE_CITATIONS={len(citation_urls)}")
    print("URL_FACTCHECK_SMOKE_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("LANGGRAPH_BASE_URL", "http://localhost:2024"),
    )
    parser.add_argument("--url", default="https://example.com")
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.url))


if __name__ == "__main__":
    main()
