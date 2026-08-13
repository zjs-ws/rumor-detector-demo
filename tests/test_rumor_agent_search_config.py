"""Regression tests for RumorBuster web-search capability wiring."""

from pathlib import Path
from types import SimpleNamespace

import yaml

from deerflow.agents import rumor_agent
from deerflow.subagents.builtins import RUMOR_WEB_RESEARCHER_CONFIG
from deerflow.subagents.builtins.rumor_web_researcher import build_web_search_input


def test_example_config_enables_keyless_duckduckgo_search():
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))

    web_search = next(tool for tool in config["tools"] if tool["name"] == "web_search")
    web_fetch = next(tool for tool in config["tools"] if tool["name"] == "web_fetch")

    assert web_search["use"] == "deerflow.community.ddg_search.tools:web_search_tool"
    assert web_search["max_results"] == 5
    assert web_fetch["use"] == "deerflow.community.jina_ai.tools:web_fetch_tool"
    assert web_fetch["timeout"] == 12
    assert web_fetch["max_chars"] == 12000
    assert config["subagents"]["agents"]["web-researcher"]["timeout_seconds"] == 55
    assert config["subagents"]["agents"]["authority-researcher"]["timeout_seconds"] == 55
    assert config["subagents"]["agents"]["evidence-critic"]["timeout_seconds"] == 20


def test_main_agent_delegates_search_instead_of_using_search_tools_directly():
    base_tools = [
        SimpleNamespace(name="web_search"),
        SimpleNamespace(name="web_fetch"),
        SimpleNamespace(name="task"),
        SimpleNamespace(name="ask_clarification"),
    ]

    selected = rumor_agent._select_main_agent_tools(  # noqa: SLF001
        base_tools,
        classifier_enabled=False,
        web_fetch_enabled=True,
    )

    assert [tool.name for tool in selected] == [
        "web_fetch",
        "task",
        "ask_clarification",
        "classify_checkability",
        "retrieve_verified_rumors",
        "assess_evidence",
    ]


def test_main_agent_hides_web_fetch_when_not_configured():
    selected = rumor_agent._select_main_agent_tools(  # noqa: SLF001
        [SimpleNamespace(name="web_search"), SimpleNamespace(name="web_fetch")],
        classifier_enabled=False,
        web_fetch_enabled=False,
    )

    assert [tool.name for tool in selected] == [
        "classify_checkability",
        "retrieve_verified_rumors",
        "assess_evidence",
    ]


def test_classifier_is_only_added_when_explicitly_enabled():
    selected = rumor_agent._select_main_agent_tools(  # noqa: SLF001
        [SimpleNamespace(name="task")],
        classifier_enabled=True,
        web_fetch_enabled=False,
    )

    assert [tool.name for tool in selected] == [
        "task",
        "rumor_check",
        "classify_checkability",
        "retrieve_verified_rumors",
        "assess_evidence",
    ]


def test_web_researcher_has_bounded_search_and_fetch_budgets():
    assert RUMOR_WEB_RESEARCHER_CONFIG.max_tool_calls == 5
    assert RUMOR_WEB_RESEARCHER_CONFIG.max_turns == 7
    assert RUMOR_WEB_RESEARCHER_CONFIG.direct_tool is None
    assert RUMOR_WEB_RESEARCHER_CONFIG.tool_call_limits == {
        "web_search": 1,
        "web_fetch": 4,
    }

    tool_input = build_web_search_input("请核验以下主张：OpenAI 的官方 GitHub 组织地址是 https://github.com/openai/。\n请列出来源。")

    assert tool_input == {
        "query": "OpenAI 的官方 GitHub 组织地址是 https://github.com/openai/。",
        "max_results": 5,
    }
