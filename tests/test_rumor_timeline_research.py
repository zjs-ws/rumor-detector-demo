"""Tests for the deterministic propagation-research branch."""

from __future__ import annotations

import asyncio
import json

from deerflow.agents.rumor_agent import graph_v3
from deerflow.agents.rumor_agent.timeline_research import (
    extract_timeline_date,
    infer_timeline_event_type,
    parse_search_results,
    timeline_candidate_relevant,
)


class _FakeTool:
    def __init__(self, name: str, handler):
        self.name = name
        self._handler = handler

    async def ainvoke(self, payload):
        return self._handler(payload)


def test_timeline_helpers_parse_public_results_dates_and_event_types():
    results = parse_search_results(
        json.dumps(
            {
                "results": [
                    {
                        "title": "旧说法再次传播",
                        "url": "https://news.example/2024/05/06/item",
                        "content": "辟谣页面",
                    },
                    {"title": "非法", "url": "javascript:alert(1)", "content": ""},
                ]
            }
        )
    )

    assert len(results) == 1
    assert extract_timeline_date("发布时间：2024年5月6日") == "2024-05-06"
    assert infer_timeline_event_type("这条旧谣言再次传播") == "resurgence"
    assert infer_timeline_event_type("官方发布辟谣说明") == "correction"
    assert timeline_candidate_relevant("疏通剂遇热水会喷溅", "管道疏通剂不能加入热水，可能喷溅") is True
    assert timeline_candidate_relevant("疏通剂遇热水会喷溅", "新冠病毒不能在炎热气候传播") is False
    assert timeline_candidate_relevant("疏通剂、洁厕灵遇热水可能喷溅", "洁厕灵有消毒作用吗") is False


def test_timeline_service_uses_direct_tools_without_model_loop(monkeypatch):
    search_results = [
        {
            "title": f"传播记录 {index}",
            "url": f"https://source-{index}.example/2024/0{index}/0{index}/article",
            "content": "某公开说法传播记录",
        }
        for index in range(1, 4)
    ]

    def search_handler(payload):
        assert payload["query"].endswith("最早 网传 辟谣 传播")
        assert payload["max_results"] == 5
        return json.dumps({"results": search_results})

    def fetch_handler(payload):
        index = payload["url"].split("source-")[1][0]
        return json.dumps(
            {
                "source_url": payload["url"],
                "title": f"传播记录 {index}",
                "published_at": f"2024-0{index}-0{index}",
                "fetched_at": "2026-08-14T12:00:00+08:00",
                "content": "该页面记录了某公开说法的公开传播。",
            }
        )

    tools = [
        _FakeTool("web_search", search_handler),
        _FakeTool("web_fetch", fetch_handler),
    ]
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: tools)
    monkeypatch.setattr(graph_v3, "_model_name", lambda: "fake-model")
    services = graph_v3.RumorV3Services(
        web_search_enabled=True,
        web_fetch_enabled=True,
        classifier_enabled=False,
    )

    result = asyncio.run(
        services.research_timeline(
            {
                "normalized_claim": "某公开说法",
                "subclaims": [{"id": "claim-1", "text": "某公开说法", "material": True}],
            },
            {},
        )
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 3
    assert all(item["timeline_only"] is True for item in result["evidence"])
    assert all(item["stance"] == "context" for item in result["evidence"])
    assert [item["published_at"] for item in result["evidence"]] == [
        "2024-01-01",
        "2024-02-02",
        "2024-03-03",
    ]
