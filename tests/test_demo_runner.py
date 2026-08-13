"""Contract tests for repeatable V2/V3 demonstration capture."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_demo_cases.py"
    spec = importlib.util.spec_from_file_location("rumorbuster_demo_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_manifest_has_boundary_professional_and_url_cases():
    runner = _load_runner()
    cases = runner.load_cases(Path(__file__).resolve().parents[1] / "evaluation" / "demo_cases.json")

    assert [case["category"] for case in cases] == ["boundary", "professional", "url"]
    assert len({case["id"] for case in cases}) == 3
    assert cases[1]["expected"]["authority_branch"] == "attempted"
    assert cases[2]["source_url"].startswith("https://")


def test_validate_capture_accepts_traceable_v3_report():
    runner = _load_runner()
    artifact = {
        "workflow": {
            "stage": "report",
            "branch_status": {
                "rag": {"status": "completed"},
                "web": {"status": "completed"},
                "authority": {"status": "completed"},
            },
            "rag_result": {"matches": [{"record_id": "who-covid-007"}]},
            "decision": {"verdict": "谣言"},
        },
        "report": {
            "schema_version": "rumorbuster-report-v3",
            "domain_route": {"domain": "medical"},
            "evidence": [{"id": "web-1", "url": "https://www.who.int/a"}],
            "decision": {"verdict": "谣言", "accepted_evidence_ids": ["web-1"]},
            "timeline": {
                "timeline_status": "ready",
                "events": [{"evidence_id": "web-1", "url": "https://www.who.int/a"}],
            },
        },
        "observed_urls": ["https://www.who.int/a"],
        "tool_messages": [{"name": "web_fetch", "content": "https://www.who.int/a"}],
    }
    checks = runner.validate_capture(
        artifact,
        {
            "id": "medical-old-rumor",
            "expected": {
                "domain": "medical",
                "authority_branch": "attempted",
                "rag_record_id": "who-covid-007",
            },
        },
    )

    assert all(checks.values())


def test_validate_capture_rejects_unobserved_report_url():
    runner = _load_runner()
    artifact = {
        "workflow": {"stage": "report", "decision": {"verdict": "证据不足"}},
        "report": {
            "schema_version": "rumorbuster-report-v3",
            "evidence": [{"id": "invented", "url": "https://invented.invalid/a"}],
            "decision": {"verdict": "证据不足"},
            "timeline": {"timeline_status": "insufficient", "events": []},
        },
        "observed_urls": [],
        "tool_messages": [],
    }

    checks = runner.validate_capture(artifact, {"id": "unobserved", "expected": {}})
    assert checks["observed_urls_only"] is False


def test_build_prompt_preserves_claim_and_optional_source():
    runner = _load_runner()
    assert runner.build_prompt({"claim": "待核验主张"}) == "请核验以下主张：\n待核验主张"
    prompt = runner.build_prompt({"claim": "待核验主张", "source_url": "https://example.com/a"})
    assert "待核验主张" in prompt
    assert "来源页面：https://example.com/a" in prompt
