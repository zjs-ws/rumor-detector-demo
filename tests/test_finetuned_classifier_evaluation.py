from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate_finetuned_classifier.py"
    spec = importlib.util.spec_from_file_location("evaluate_finetuned_classifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metrics_reports_three_class_macro_f1_and_failures():
    module = _load_module()
    rows = [
        {
            "true_label": "rumor",
            "prediction": "rumor",
            "raw_response": "Yes",
            "latency_ms": 10,
        },
        {
            "true_label": "non_rumor",
            "prediction": "non_rumor",
            "raw_response": "No",
            "latency_ms": 20,
        },
        {
            "true_label": "unknown",
            "prediction": None,
            "raw_response": "ERROR:TimeoutError",
            "latency_ms": 30,
        },
    ]

    result = module.metrics(rows)

    assert result["accuracy"] == 2 / 3
    assert result["macro_f1"] == 2 / 3
    assert result["service_failure_rate"] == 1 / 3
    assert result["invalid_output_rate"] == 0
    assert result["latency_ms"] == {"mean": 20, "p50": 20.0, "p95": 30.0}


def test_adversarial_comparison_reports_drop_and_prediction_consistency():
    module = _load_module()
    rows = [
        {
            "true_label": "rumor",
            "prediction": "non_rumor",
            "raw_response": "No",
            "latency_ms": 12,
            "original_prediction": "rumor",
            "original_raw_response": "Yes",
            "original_latency_ms": 10,
        },
        {
            "true_label": "non_rumor",
            "prediction": "non_rumor",
            "raw_response": "No",
            "latency_ms": 11,
            "original_prediction": "non_rumor",
            "original_raw_response": "No",
            "original_latency_ms": 9,
        },
    ]

    comparison = module.build_adversarial_comparison(rows, module.metrics(rows))

    assert comparison["original_metrics"]["accuracy"] == 1
    assert comparison["perturbed_metrics"]["accuracy"] == 0.5
    assert comparison["accuracy_drop"] == 0.5
    assert comparison["prediction_consistency"] == 0.5
    assert "不代表自然网络分布" in comparison["note"]


def test_smoke_fixture_has_balanced_labels_and_two_mixed_cases():
    path = Path(__file__).resolve().parents[1] / "evaluation/model_smoke_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert len(cases) == 9
    assert [item["expected_raw_label"] for item in cases].count("Yes") == 3
    assert [item["expected_raw_label"] for item in cases].count("No") == 3
    assert [item["expected_raw_label"] for item in cases].count("Unknown") == 3
    assert sum(item["kind"] == "mixed_subclaims" for item in cases) >= 2
