"""Tests for the transparent local TF-IDF rumor retriever."""

import json

from deerflow.agents.rumor_agent.rag import (
    _load_index,
    retrieve_verified_rumors,
    retrieve_verified_rumors_tool,
)


def test_reviewed_knowledge_base_has_at_least_thirty_records():
    records, _, _ = _load_index()
    assert len(records) >= 30
    assert all(record["review_status"] == "reviewed" for record in records)


def test_close_variant_returns_top_three_non_authoritative_matches():
    result = retrieve_verified_rumors("喝高度酒可以杀死新冠病毒", threshold=0.05)

    assert result.status == "ok"
    assert 1 <= len(result.matches) <= 3
    assert result.authoritative is False
    assert "酒精" in result.matches[0].canonical_claim or "酒" in result.matches[0].matched_variant


def test_unrelated_claim_returns_no_match_at_normal_threshold():
    result = retrieve_verified_rumors("某城市下周三地铁将临时调整末班车时间")
    assert result.status == "no_match"


def test_tool_accepts_workflow_locked_threshold_for_expanded_claim():
    result = json.loads(
        retrieve_verified_rumors_tool.invoke(
            {
                "claim": "饮酒可以预防感染新冠肺炎（COVID-19）",
                "top_k": 3,
                "threshold": 0.05,
            }
        )
    )
    assert result["threshold"] == 0.05
    assert result["matches"][0]["record_id"] == "who-covid-007"
