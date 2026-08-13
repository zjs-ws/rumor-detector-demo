#!/usr/bin/env python3
"""Run a real URL fact-check against V3 or the V2 rollback graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from langgraph_sdk import get_client
from run_demo_cases import _extract_capture, _normalize_url, validate_capture


async def run(base_url: str, target_url: str, graph_id: str) -> None:
    client = get_client(url=base_url)
    assistants = await client.assistants.search(graph_id=graph_id)
    if not assistants:
        raise RuntimeError(f"{graph_id} assistant was not found")

    thread = await client.threads.create()
    result = await asyncio.wait_for(
        client.runs.wait(
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
            on_disconnect="continue",
        ),
        timeout=120,
    )

    artifact: dict[str, Any] = _extract_capture(dict(result))
    checks = validate_capture(
        artifact,
        {
            "id": "url-smoke",
            "expected": {"original_page": "attempted"},
        },
    )
    workflow = artifact["workflow"]
    report = artifact["report"]
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"URL workflow failed checks: {', '.join(failed)}")

    original = workflow.get("original_page") or report.get("original_page") or {}
    preserved_urls = {
        _normalize_url(str(original[key]))
        for key in ("source_url", "requested_url")
        if original.get(key)
    }
    if workflow.get("source_url"):
        preserved_urls.add(_normalize_url(str(workflow["source_url"])))
    if _normalize_url(target_url) not in preserved_urls:
        raise RuntimeError("structured report did not preserve the requested source URL")
    if not report.get("decision"):
        raise RuntimeError("structured URL report omitted the binding decision")

    print(artifact["final_response"])
    print(
        json.dumps(
            {
                "graph_id": graph_id,
                "schema_version": report.get("schema_version"),
                "workflow_stage": workflow.get("stage"),
                "verdict": report["decision"].get("verdict"),
                "observed_url_count": len(artifact["observed_urls"]),
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("URL_FACTCHECK_SMOKE_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("LANGGRAPH_BASE_URL", "http://localhost:2024"),
    )
    parser.add_argument("--graph-id", default="rumor_agent")
    parser.add_argument("--url", default="https://example.com")
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.url, args.graph_id))


if __name__ == "__main__":
    main()
