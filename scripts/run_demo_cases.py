#!/usr/bin/env python3
"""Capture repeatable RumorBuster V2/V3 demonstration runs.

The runner creates an independent LangGraph thread for every case and repeat,
keeps failures isolated, and writes only redacted, reviewable artifacts.  It is
intended for course demonstrations and regression comparison rather than load
testing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

_PLAIN_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)\]]+")
_SUPPORTED_CATEGORIES = {"boundary", "professional", "url"}
_SUPPORTED_SCHEMAS = {"rumorbuster-report-v2", "rumorbuster-report-v3"}
_TERMINAL_STAGES = {"report", "needs_input", "conversation"}
_ATTEMPTED_STATUSES = {"completed", "unavailable"}


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _normalize_url(value: str) -> str:
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


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)
    if hasattr(message, "model_dump"):
        dumped = message.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {"content": dumped}
    return {
        "type": getattr(message, "type", None),
        "name": getattr(message, "name", None),
        "content": getattr(message, "content", ""),
        "tool_call_id": getattr(message, "tool_call_id", None),
    }


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("text")
        )
    return str(content)


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate the stable demonstration manifest."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("demo manifest must be a non-empty JSON array")

    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"demo case {index + 1} must be an object")
        case_id = str(item.get("id") or "").strip()
        claim = str(item.get("claim") or "").strip()
        category = str(item.get("category") or "").strip()
        if not case_id or case_id in ids:
            raise ValueError(f"demo case {index + 1} has a missing or duplicate id")
        if not claim:
            raise ValueError(f"demo case {case_id} has no claim")
        if category not in _SUPPORTED_CATEGORIES:
            raise ValueError(f"demo case {case_id} has unsupported category {category!r}")
        source_url = item.get("source_url")
        if source_url is not None:
            parsed = urlsplit(str(source_url))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"demo case {case_id} has an invalid source_url")
        ids.add(case_id)
        cases.append(dict(item))
    return cases


def build_prompt(case: dict[str, Any]) -> str:
    """Build the same public input used by the Gateway API."""

    prompt = f"请核验以下主张：\n{str(case['claim']).strip()}"
    source_url = case.get("source_url")
    if source_url:
        prompt += f"\n\n来源页面：{source_url}"
    return prompt


def _evidence_urls(report: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for item in report.get("evidence", []) or []:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            urls.add(_normalize_url(item["url"]))
    timeline = _as_dict(report.get("timeline"))
    for event in timeline.get("events", []) or []:
        if isinstance(event, dict) and isinstance(event.get("url"), str):
            urls.add(_normalize_url(event["url"]))
    return urls


def _rag_record_ids(workflow: dict[str, Any], report: dict[str, Any]) -> set[str]:
    rag = workflow.get("rag_result") or report.get("rag") or {}
    if not isinstance(rag, dict):
        return set()
    return {
        str(item["record_id"])
        for item in rag.get("matches", []) or []
        if isinstance(item, dict) and item.get("record_id")
    }


def _branch_status(workflow: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    value = workflow.get("branch_status") or report.get("research_branches") or {}
    return _as_dict(value)


def validate_capture(
    artifact: dict[str, Any], case: dict[str, Any]
) -> dict[str, bool]:
    """Validate deterministic invariants and case-specific expectations."""

    workflow = _as_dict(artifact.get("workflow"))
    report = _as_dict(artifact.get("report"))
    decision = _as_dict(report.get("decision"))
    workflow_decision = _as_dict(workflow.get("decision"))
    schema = report.get("schema_version")
    observed = {
        _normalize_url(str(url))
        for url in artifact.get("observed_urls", []) or []
        if isinstance(url, str) and url.startswith(("http://", "https://"))
    }
    evidence_ids = {
        str(item.get("id"))
        for item in report.get("evidence", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    timeline_events = _as_dict(report.get("timeline")).get("events", []) or []

    checks = {
        "terminal_stage": workflow.get("stage") in _TERMINAL_STAGES,
        "report_schema_supported": schema in _SUPPORTED_SCHEMAS,
        "decision_bound": bool(decision.get("verdict"))
        and (
            not workflow_decision.get("verdict")
            or workflow_decision.get("verdict") == decision.get("verdict")
        ),
        "observed_urls_only": _evidence_urls(report) <= observed,
        "timeline_traceable": all(
            isinstance(event, dict)
            and (
                str(event.get("evidence_id", "")) in evidence_ids
                or str(event.get("evidence_id", "")).startswith("rag:")
            )
            for event in timeline_events
        ),
    }

    expected = _as_dict(case.get("expected"))
    if expected.get("verdict") is not None:
        checks["expected_verdict"] = decision.get("verdict") == expected["verdict"]
    if expected.get("domain") is not None:
        domain_route = _as_dict(report.get("domain_route"))
        claim_context = _as_dict(workflow.get("claim_context"))
        actual_domain = domain_route.get("domain") or claim_context.get("domain")
        checks["expected_domain"] = actual_domain == expected["domain"]
    if expected.get("external_calls") is not None:
        checks["expected_external_calls"] = (
            len(artifact.get("tool_messages", []) or [])
            == int(expected["external_calls"])
        )
    if expected.get("authority_branch") == "attempted":
        authority = _as_dict(_branch_status(workflow, report).get("authority"))
        checks["expected_authority_branch"] = (
            authority.get("status") in _ATTEMPTED_STATUSES
        )
    if expected.get("rag_record_id") is not None:
        checks["expected_rag_record"] = (
            str(expected["rag_record_id"]) in _rag_record_ids(workflow, report)
        )
    if expected.get("original_page") == "attempted":
        original = workflow.get("original_page") or report.get("original_page")
        degradations = workflow.get("degradation_codes", []) or []
        trace_stages = {
            str(item.get("stage"))
            for item in workflow.get("trace", []) or []
            if isinstance(item, dict)
        }
        checks["expected_original_page"] = bool(original) or (
            "fetch_original" in trace_stages
            or any("original" in str(code) for code in degradations)
        )
    return checks


def _extract_capture(result: dict[str, Any]) -> dict[str, Any]:
    messages = [_message_dict(item) for item in result.get("messages", []) or []]
    tool_messages = []
    observed_urls: set[str] = set()
    for message in messages:
        if message.get("type") not in {"tool", "ToolMessage"}:
            continue
        content = _message_text(message)
        tool_messages.append(
            {
                "name": message.get("name"),
                "tool_call_id": message.get("tool_call_id"),
                "content": content[:20_000],
                "truncated": len(content) > 20_000,
            }
        )
        observed_urls.update(_PLAIN_URL_PATTERN.findall(content))

    research_payloads: dict[str, Any] = {}
    for state_key, label in (
        ("v3_web_research", "web"),
        ("v3_authority_research", "authority"),
        ("v3_supplement_research", "supplement"),
    ):
        payload = result.get(state_key)
        if not isinstance(payload, dict):
            continue
        research_payloads[label] = payload
        observed_urls.update(
            str(url) for url in payload.get("observed_urls", []) or [] if url
        )

    workflow = _as_dict(result.get("rumor_workflow"))
    report = _as_dict(result.get("rumor_report"))
    original = workflow.get("original_page") or report.get("original_page")
    if isinstance(original, dict):
        for key in ("source_url", "requested_url", "url"):
            if original.get(key):
                observed_urls.add(str(original[key]))

    final_text = next(
        (
            _message_text(message)
            for message in reversed(messages)
            if message.get("type") in {"ai", "assistant", "AIMessage"}
        ),
        "",
    )
    return {
        "workflow": workflow,
        "report": report,
        "observed_urls": sorted({_normalize_url(url) for url in observed_urls}),
        "tool_messages": tool_messages,
        "research_payloads": research_payloads,
        "final_response": final_text,
    }


async def _run_one(
    client: Any,
    assistant_id: str,
    graph_id: str,
    case: dict[str, Any],
    repeat: int,
    timeout: float,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    started_clock = time.monotonic()
    artifact: dict[str, Any] = {
        "artifact_version": "rumorbuster-demo-capture-v1",
        "graph_id": graph_id,
        "case_id": case["id"],
        "case_title": case.get("title", case["id"]),
        "category": case["category"],
        "repeat": repeat,
        "input": {
            "claim": case["claim"],
            "source_url": case.get("source_url"),
        },
        "started_at": started_at.isoformat(),
        "thread_id_redacted": True,
        "status": "failed",
    }
    try:
        thread = await client.threads.create()
        result = await asyncio.wait_for(
            client.runs.wait(
                thread["thread_id"],
                assistant_id,
                input={
                    "messages": [
                        {"role": "human", "content": build_prompt(case)}
                    ]
                },
                config={"recursion_limit": 100},
                on_disconnect="continue",
            ),
            timeout=timeout,
        )
        artifact.update(_extract_capture(dict(result)))
        artifact["status"] = "completed"
    except TimeoutError:
        artifact["status"] = "timeout"
        artifact["error"] = f"run exceeded {timeout:g} seconds"
    except Exception as exc:  # Each case must leave an artifact and not abort the suite.
        artifact["status"] = "failed"
        artifact["error"] = f"{type(exc).__name__}: {exc}"

    artifact["finished_at"] = datetime.now(UTC).isoformat()
    artifact["duration_ms"] = round((time.monotonic() - started_clock) * 1000)
    artifact["checks"] = validate_capture(artifact, case)
    artifact["all_checks_passed"] = bool(artifact["checks"]) and all(
        artifact["checks"].values()
    )
    return artifact


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# RumorBuster V2/V3 演示运行摘要",
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "| 图 | 案例 | 次数 | 状态 | 结论 | 领域 | 耗时(ms) | 校验 |",
        "|---|---|---:|---|---|---|---:|---|",
    ]
    for item in summary["runs"]:
        lines.append(
            "| {graph_id} | {case_id} | {repeat} | {status} | {verdict} | "
            "{domain} | {duration_ms} | {checks} |".format(**item)
        )
    lines.extend(
        [
            "",
            "> 每次运行使用独立线程；文件不保存 thread_id、密钥或完整环境变量。",
            "",
        ]
    )
    return "\n".join(lines)


async def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    from langgraph_sdk import get_client

    cases = load_cases(args.manifest)
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            raise ValueError(f"unknown demo case(s): {', '.join(sorted(missing))}")

    client = get_client(url=args.base_url)
    assistant_ids: dict[str, str] = {}
    for graph_id in args.graphs:
        assistants = await client.assistants.search(graph_id=graph_id)
        if not assistants:
            assistant_ids[graph_id] = ""
            continue
        assistant_ids[graph_id] = str(assistants[0]["assistant_id"])

    artifacts: list[dict[str, Any]] = []
    for graph_id in args.graphs:
        assistant_id = assistant_ids[graph_id]
        for case in cases:
            for repeat in range(1, args.repeats + 1):
                if assistant_id:
                    artifact = await _run_one(
                        client,
                        assistant_id,
                        graph_id,
                        case,
                        repeat,
                        args.timeout,
                    )
                else:
                    artifact = {
                        "artifact_version": "rumorbuster-demo-capture-v1",
                        "graph_id": graph_id,
                        "case_id": case["id"],
                        "case_title": case.get("title", case["id"]),
                        "category": case["category"],
                        "repeat": repeat,
                        "input": {
                            "claim": case["claim"],
                            "source_url": case.get("source_url"),
                        },
                        "status": "assistant_unavailable",
                        "thread_id_redacted": True,
                        "checks": {},
                        "all_checks_passed": False,
                        "error": f"graph {graph_id!r} is not available",
                    }
                artifacts.append(artifact)
                _write_json(
                    args.output_dir
                    / f"{case['id']}--{graph_id}--run-{repeat}.json",
                    artifact,
                )

    summary_runs = []
    for artifact in artifacts:
        report = _as_dict(artifact.get("report"))
        domain_route = _as_dict(report.get("domain_route"))
        summary_runs.append(
            {
                "graph_id": artifact["graph_id"],
                "case_id": artifact["case_id"],
                "repeat": artifact["repeat"],
                "status": artifact["status"],
                "verdict": _as_dict(report.get("decision")).get("verdict", "—"),
                "domain": domain_route.get("domain", "—"),
                "duration_ms": artifact.get("duration_ms", "—"),
                "checks": "通过" if artifact.get("all_checks_passed") else "需检查",
            }
        )
    summary = {
        "schema_version": "rumorbuster-demo-summary-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "graphs": args.graphs,
        "repeats": args.repeats,
        "runs": summary_runs,
        "passed": sum(bool(item.get("all_checks_passed")) for item in artifacts),
        "total": len(artifacts),
    }
    _write_json(args.output_dir / "summary.json", summary)
    (args.output_dir / "summary.md").write_text(
        _summary_markdown(summary), encoding="utf-8"
    )
    return summary


def _parse_args() -> argparse.Namespace:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(
        description="Capture repeatable V2/V3 RumorBuster demonstration runs"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LANGGRAPH_BASE_URL", "http://localhost:2024"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("evaluation/demo_cases.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/demo_runs") / timestamp,
    )
    parser.add_argument(
        "--graphs",
        nargs="+",
        default=["rumor_agent_v2", "rumor_agent"],
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--case", action="append")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any run fails its validation checks",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main() -> None:
    args = _parse_args()
    summary = asyncio.run(run_suite(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Artifacts: {args.output_dir}")
    if args.strict and summary["passed"] != summary["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
