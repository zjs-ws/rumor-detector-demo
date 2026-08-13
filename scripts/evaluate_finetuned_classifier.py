#!/usr/bin/env python3
"""Evaluate the frozen course classifier through its real ModelScope API.

This script never edits datasets and never substitutes mock predictions. Output
is written to a separate evaluation directory with request-level audit data.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EARLY = ROOT / "模型微调/bench mark/早期预警准确率（1）/早期预警测试集.json"
ADVERSARIAL = ROOT / "模型微调/bench mark/对抗扰动抵抗度（4）/对抗测试集.json"
LABEL_MAP = {"Yes": "rumor", "No": "non_rumor", "Unknown": "unknown"}
INSTRUCTION = (
    "You are a professional rumor detection assistant. Determine whether the "
    "following text is a rumor. You must strictly output only one of the "
    "following options: 'Yes', 'No', or 'Unknown'. If there is not enough "
    "information to verify the claim, output 'Unknown'."
)


def classify(base_url: str, text: str, timeout: float) -> tuple[str | None, str, int, dict]:
    body = json.dumps(
        {
            "messages": [
                {"role": "system", "content": INSTRUCTION},
                {"role": "user", "content": text},
            ],
            "max_new_tokens": 8,
            "temperature": 0,
            "top_p": 1,
            "top_k": 20,
            "repetition_penalty": 1,
        }
    ).encode()
    endpoint = base_url.rstrip("/")
    endpoint = f"{endpoint}/chat" if endpoint.endswith("/v1") else f"{endpoint}/v1/chat"
    started = time.monotonic()
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
        raw = str(payload.get("response", "")).strip().strip("'\".,!?。！？")
        prediction = LABEL_MAP.get(raw)
        return prediction, raw, round((time.monotonic() - started) * 1000), payload.get("usage", {})
    except (OSError, ValueError, KeyError, urllib.error.HTTPError) as exc:
        return None, f"ERROR:{type(exc).__name__}", round((time.monotonic() - started) * 1000), {}


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))])


def metrics(rows: list[dict]) -> dict:
    labels = ("rumor", "non_rumor", "unknown")
    valid = [row for row in rows if row["prediction"] in labels]
    per_class = {}
    for label in labels:
        tp = sum(row["true_label"] == label == row["prediction"] for row in valid)
        fp = sum(row["true_label"] != label and row["prediction"] == label for row in valid)
        fn = sum(row["true_label"] == label and row["prediction"] != label for row in valid)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1}
    latencies = [row["latency_ms"] for row in rows]
    matrix = {actual: Counter(row["prediction"] or "service_failure" for row in rows if row["true_label"] == actual) for actual in labels}
    return {
        "sample_count": len(rows),
        "accuracy": sum(row["prediction"] == row["true_label"] for row in rows) / len(rows) if rows else 0.0,
        "macro_f1": statistics.mean(value["f1"] for value in per_class.values()),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "invalid_output_rate": sum(row["prediction"] is None and not row["raw_response"].startswith("ERROR:") for row in rows) / len(rows) if rows else 0.0,
        "service_failure_rate": sum(row["raw_response"].startswith("ERROR:") for row in rows) / len(rows) if rows else 0.0,
        "latency_ms": {
            "mean": statistics.mean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        },
    }


def build_adversarial_comparison(rows: list[dict], perturbed_metrics: dict) -> dict:
    original_rows = [
        {
            "true_label": row["true_label"],
            "prediction": row["original_prediction"],
            "raw_response": row["original_raw_response"],
            "latency_ms": row["original_latency_ms"],
        }
        for row in rows
    ]
    original_metrics = metrics(original_rows)
    return {
        "original_metrics": original_metrics,
        "perturbed_metrics": perturbed_metrics,
        "accuracy_drop": original_metrics["accuracy"] - perturbed_metrics["accuracy"],
        "prediction_consistency": sum(row["prediction"] == row["original_prediction"] for row in rows) / len(rows) if rows else 0.0,
        "note": "人工合成压力测试，不代表自然网络分布。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--dataset", choices=("early", "adversarial"), default="early")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/model_runs")
    args = parser.parse_args()
    source = EARLY if args.dataset == "early" else ADVERSARIAL
    records = json.loads(source.read_text(encoding="utf-8"))
    if args.limit is not None:
        records = records[: max(0, args.limit)]
    rows = []
    for index, record in enumerate(records, 1):
        prediction, raw, latency_ms, usage = classify(args.base_url, record["text"], args.timeout)
        row = {
            "index": index,
            "true_label": record["true_label"],
            "prediction": prediction,
            "raw_response": raw,
            "latency_ms": latency_ms,
            "usage": usage,
            "perturbation_log": record.get("perturbation_log"),
        }
        if args.dataset == "adversarial":
            original_prediction, original_raw, original_latency, original_usage = classify(args.base_url, record["original_text"], args.timeout)
            row.update(
                {
                    "original_prediction": original_prediction,
                    "original_raw_response": original_raw,
                    "original_latency_ms": original_latency,
                    "original_usage": original_usage,
                }
            )
        rows.append(row)
        print(f"[{index}/{len(records)}] true={record['true_label']} predicted={prediction or raw} {latency_ms}ms")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": args.dataset,
        "dataset_path": str(source.relative_to(ROOT)),
        "api_style": "modelscope_chat",
        "temperature": 0,
        "mock": False,
        "metrics": metrics(rows),
        "rows": rows,
    }
    if args.dataset == "adversarial":
        result["adversarial_comparison"] = build_adversarial_comparison(rows, result["metrics"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.dataset}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {output}")
    return 0 if result["metrics"]["service_failure_rate"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
