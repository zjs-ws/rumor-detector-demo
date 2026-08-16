#!/usr/bin/env python3
"""Run and score the 30-case live RumorBuster acceptance suite.

This is intentionally separate from component and mock tests. Every artifact is
created by a fresh LangGraph thread against the configured live services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph_sdk import get_client

from run_demo_cases import _as_dict, _normalize_url, _run_one, _write_json, load_cases

_DECISIVE = {"谣言", "非谣言", "误导"}


def _evidence_audit(artifact: dict[str, Any]) -> dict[str, int]:
    report = _as_dict(artifact.get("report"))
    workflow = _as_dict(artifact.get("workflow"))
    observed = set(artifact.get("observed_urls", []) or [])
    accepted_ids = set(
        _as_dict(report.get("decision")).get("accepted_evidence_ids", []) or []
    )
    fake_urls = 0
    direct_without_excerpt = 0
    for item in report.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        if _normalize_url(str(item.get("url") or "")) not in observed:
            fake_urls += 1
        if item.get("id") in accepted_ids and (
            item.get("directness") != "direct"
            or not str(item.get("excerpt") or "").strip()
            or item.get("fetch_status") != "fetched"
            or len(str(item.get("document_hash") or "")) != 64
        ):
            direct_without_excerpt += 1
    rule_mismatch = int(
        bool(_as_dict(workflow.get("decision")).get("verdict"))
        and _as_dict(workflow.get("decision")).get("verdict")
        != _as_dict(report.get("decision")).get("verdict")
    )
    return {
        "fake_urls": fake_urls,
        "accepted_without_verified_excerpt": direct_without_excerpt,
        "rule_report_mismatches": rule_mismatch,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.manifest)
    if len(cases) != 30:
        raise ValueError(f"live acceptance manifest must contain exactly 30 cases, got {len(cases)}")
    client = get_client(url=args.base_url)
    assistants = await client.assistants.search(graph_id=args.graph)
    if not assistants:
        raise RuntimeError(f"graph {args.graph!r} is unavailable at {args.base_url}")
    assistant_id = str(assistants[0]["assistant_id"])

    artifacts: list[dict[str, Any]] = []
    for case in cases:
        artifact = await _run_one(
            client, assistant_id, args.graph, case, 1, args.timeout
        )
        artifact["evidence_audit"] = _evidence_audit(artifact)
        artifacts.append(artifact)
        _write_json(args.output_dir / f"{case['id']}.json", artifact)

    resolvable = [
        (case, artifact)
        for case, artifact in zip(cases, artifacts, strict=True)
        if case.get("authoritatively_resolvable")
    ]
    decided = [
        (case, artifact)
        for case, artifact in resolvable
        if _as_dict(_as_dict(artifact.get("report")).get("decision")).get("verdict")
        in _DECISIVE
    ]
    correct_decided = sum(
        _as_dict(_as_dict(artifact.get("report")).get("decision")).get("verdict")
        == _as_dict(case.get("expected")).get("verdict")
        for case, artifact in decided
    )
    audit_totals = {
        key: sum(item["evidence_audit"][key] for item in artifacts)
        for key in (
            "fake_urls",
            "accepted_without_verified_excerpt",
            "rule_report_mismatches",
        )
    }
    decisive_rate = len(decided) / len(resolvable) if resolvable else 0.0
    conditional_accuracy = correct_decided / len(decided) if decided else 0.0
    summary = {
        "schema_version": "rumorbuster-real-e2e-evaluation-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "run_kind": "live_end_to_end_not_mock",
        "graph": args.graph,
        "total_cases": len(cases),
        "authoritatively_resolvable_cases": len(resolvable),
        "decided_resolvable_cases": len(decided),
        "decisive_rate": round(decisive_rate, 4),
        "correct_decided_cases": correct_decided,
        "conditional_accuracy": round(conditional_accuracy, 4),
        **audit_totals,
        "thresholds": {
            "decisive_rate_at_least_0_80": decisive_rate >= 0.80,
            "conditional_accuracy_at_least_0_90": conditional_accuracy >= 0.90,
            "fake_urls_zero": audit_totals["fake_urls"] == 0,
            "accepted_without_verified_excerpt_zero": audit_totals[
                "accepted_without_verified_excerpt"
            ]
            == 0,
            "rule_report_mismatches_zero": audit_totals["rule_report_mismatches"]
            == 0,
        },
        "cases": [
            {
                "id": case["id"],
                "status": artifact.get("status"),
                "expected": _as_dict(case.get("expected")).get("verdict"),
                "actual": _as_dict(
                    _as_dict(artifact.get("report")).get("decision")
                ).get("verdict"),
                "decision_status": _as_dict(
                    _as_dict(artifact.get("report")).get("decision")
                ).get("decision_status"),
                "duration_ms": artifact.get("duration_ms"),
            }
            for case, artifact in zip(cases, artifacts, strict=True)
        ],
    }
    _write_json(args.output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("LANGGRAPH_BASE_URL", "http://localhost:2024"),
    )
    parser.add_argument("--graph", default="rumor_agent")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("evaluation/real_e2e_cases.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/real_e2e_runs")
        / datetime.now().strftime("%Y%m%d-%H%M%S"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Artifacts: {args.output_dir}")
    if args.strict and not all(summary["thresholds"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
