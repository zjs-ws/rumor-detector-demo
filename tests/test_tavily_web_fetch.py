"""Contract tests for Tavily-backed structured webpage fetching."""

import json
from datetime import datetime

from deerflow.community.tavily import tools


def _stub_config(monkeypatch, max_chars: int = 12000):
    monkeypatch.setattr(
        tools,
        "get_app_config",
        lambda: type(
            "Config",
            (),
            {
                "get_tool_config": lambda _self, _name: type(
                    "ToolConfig",
                    (),
                    {"model_extra": {"max_chars": max_chars}},
                )()
            },
        )(),
    )


def _stub_client(monkeypatch, result: dict):
    class FakeClient:
        def extract(self, urls):
            return result

    monkeypatch.setattr(tools, "TavilyClient", lambda **kwargs: FakeClient())


def test_tavily_fetch_returns_structured_source_metadata(monkeypatch):
    _stub_config(monkeypatch)
    _stub_client(
        monkeypatch,
        {
            "results": [
                {
                    "url": "https://www.who.int/zh/news-room/fact-sheets/detail/tobacco",
                    "title": "烟草",
                    "raw_content": "烟草使用是全球可预防死亡的主要原因。",
                }
            ],
            "failed_results": [],
        },
    )

    result = tools.web_fetch_tool.invoke(
        {"url": "https://www.who.int/zh/news-room/fact-sheets/detail/tobacco"}
    )
    payload = json.loads(result)

    assert payload["source_url"] == "https://www.who.int/zh/news-room/fact-sheets/detail/tobacco"
    assert payload["requested_url"] == "https://www.who.int/zh/news-room/fact-sheets/detail/tobacco"
    assert payload["content"] == "烟草使用是全球可预防死亡的主要原因。"
    assert payload["truncated"] is False
    assert datetime.fromisoformat(payload["fetched_at"]).tzinfo is not None


def test_tavily_fetch_bounds_content_by_max_chars(monkeypatch):
    _stub_config(monkeypatch, max_chars=10)
    _stub_client(
        monkeypatch,
        {
            "results": [
                {
                    "url": "https://example.com/a",
                    "raw_content": "一二三四五六七八九十超过上限",
                }
            ],
            "failed_results": [],
        },
    )

    payload = json.loads(tools.web_fetch_tool.invoke({"url": "https://example.com/a"}))

    assert payload["content"] == "一二三四五六七八九十"
    assert payload["truncated"] is True
    assert payload["original_content_chars"] > payload["content_chars"]


def test_tavily_fetch_reports_failed_extraction(monkeypatch):
    _stub_config(monkeypatch)
    _stub_client(
        monkeypatch,
        {
            "results": [],
            "failed_results": [{"url": "https://example.com/a", "error": "timeout"}],
        },
    )

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/a"})

    assert result.startswith("Error:")
    assert "timeout" in result


def test_tavily_fetch_reports_missing_results(monkeypatch):
    _stub_config(monkeypatch)
    _stub_client(monkeypatch, {"results": [], "failed_results": []})

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/a"})

    assert result.startswith("Error:")


def test_tavily_fetch_rejects_empty_content(monkeypatch):
    _stub_config(monkeypatch)
    _stub_client(
        monkeypatch,
        {
            "results": [{"url": "https://example.com/a", "raw_content": "   "}],
            "failed_results": [],
        },
    )

    payload = json.loads(tools.web_fetch_tool.invoke({"url": "https://example.com/a"}))

    assert payload["content"] == ""
    assert payload["content_chars"] == 0
