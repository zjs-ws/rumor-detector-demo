#!/usr/bin/env python3
"""Run the nine-case, two-repeat acceptance check against the real model."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from evaluate_finetuned_classifier import LABEL_MAP, classify

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evaluation/model_smoke_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/model_runs/smoke")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if len(cases) != 9:
        raise ValueError("smoke fixture must contain exactly nine cases")
    records = []
    for case in cases:
        runs = []
        for repeat in range(1, max(1, args.repeats) + 1):
            prediction, raw, latency_ms, usage = classify(args.base_url, case["text"], args.timeout)
            runs.append(
                {
                    "repeat": repeat,
                    "raw_response": raw,
                    "mapped_label": prediction,
                    "latency_ms": latency_ms,
                    "usage": usage,
                }
            )
        raw_labels = {run["raw_response"] for run in runs}
        expected = case["expected_raw_label"]
        record = {
            "id": case["id"],
            "kind": case["kind"],
            "expected_raw_label": expected,
            "expected_mapped_label": LABEL_MAP[expected],
            "stable": len(raw_labels) == 1,
            "matches_expected": all(run["raw_response"] == expected for run in runs),
            "runs": runs,
        }
        records.append(record)
        print(f"{case['id']}: {[run['raw_response'] for run in runs]} stable={record['stable']} expected={expected}")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_style": "modelscope_chat",
        "temperature": 0,
        "mock": False,
        "case_count": len(records),
        "repeat_count": max(1, args.repeats),
        "stable_count": sum(item["stable"] for item in records),
        "expected_match_count": sum(item["matches_expected"] for item in records),
        "service_failure_count": sum(run["raw_response"].startswith("ERROR:") for item in records for run in item["runs"]),
        "records": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"smoke-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {output}")
    return 0 if result["service_failure_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
