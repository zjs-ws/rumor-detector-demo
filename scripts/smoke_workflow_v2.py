#!/usr/bin/env python3
"""Exercise the real LangGraph agent and print its deterministic workflow trace."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from langgraph_sdk import get_client


async def run(base_url: str, claim: str) -> None:
    client = get_client(url=base_url)
    assistants = await client.assistants.search(graph_id="rumor_agent_v2")
    if not assistants:
        raise RuntimeError("rumor_agent_v2 assistant was not found")
    thread = await client.threads.create()
    result = await client.runs.wait(
        thread["thread_id"],
        assistants[0]["assistant_id"],
        input={"messages": [{"role": "user", "content": claim}]},
        config={"recursion_limit": 100},
    )
    workflow = result.get("rumor_workflow") or {}
    report = result.get("rumor_report") or {}
    if workflow.get("stage") not in {"report", "needs_input"}:
        raise RuntimeError(f"workflow did not reach a terminal stage: {workflow.get('stage')}")
    if report.get("schema_version") != "rumorbuster-report-v2":
        raise RuntimeError("workflow did not produce rumorbuster-report-v2")
    if not report.get("decision"):
        raise RuntimeError("structured report did not contain a decision")
    print(
        json.dumps(
            {
                "thread_id": thread["thread_id"],
                "stage": workflow.get("stage"),
                "trace": workflow.get("trace", []),
                "verdict": report["decision"].get("verdict"),
                "schema_version": report.get("schema_version"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("WORKFLOW_V2_SMOKE_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("LANGGRAPH_BASE_URL", "http://localhost:2024"),
    )
    parser.add_argument("--claim", default="请核验：我觉得这部电影最好看")
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.claim))


if __name__ == "__main__":
    main()
