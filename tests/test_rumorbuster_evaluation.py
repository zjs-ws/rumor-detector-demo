"""Regression tests for the fixed V3 course evaluation manifest."""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path


def _load_evaluator():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_rumorbuster.py"
    spec = importlib.util.spec_from_file_location("rumorbuster_evaluator", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_comprehensive_manifest_has_fixed_course_composition():
    result = _load_evaluator().evaluate()

    assert result["dataset"]["v3_comprehensive_manifest"] == 40
    counts = Counter(item["category"] for item in result["v3_comprehensive_details"])
    assert counts == {
        "checkability_boundary": 10,
        "verified_rumor_rag": 8,
        "evidence_conflict_and_professional": 12,
        "mixed_subclaims": 5,
        "url_and_failure_flow": 5,
    }
    assert all(item["correct"] for item in result["v3_comprehensive_details"])


def test_v3_manifest_references_are_unique():
    details = _load_evaluator().evaluate()["v3_comprehensive_details"]
    assert len({item["id"] for item in details}) == 40
    assert len({(item["component"], item["case_id"]) for item in details}) == 40
