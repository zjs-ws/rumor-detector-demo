"""Regression tests for RumorBuster web-search capability wiring."""

from pathlib import Path
from types import SimpleNamespace

import yaml

from deerflow.agents import rumor_agent
from deerflow.subagents.builtins import RUMOR_WEB_RESEARCHER_CONFIG


def test_example_config_enables_keyless_duckduckgo_search():
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))

    web_search = next(tool for tool in config["tools"] if tool["name"] == "web_search")

    assert web_search["use"] == "deerflow.community.ddg_search.tools:web_search_tool"
    assert web_search["max_results"] == 5
    assert config["subagents"]["agents"]["web-researcher"]["timeout_seconds"] == 60


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
    )

    assert [tool.name for tool in selected] == ["task", "ask_clarification"]


def test_classifier_is_only_added_when_explicitly_enabled():
    selected = rumor_agent._select_main_agent_tools(  # noqa: SLF001
        [SimpleNamespace(name="task")],
        classifier_enabled=True,
    )

    assert [tool.name for tool in selected] == ["task", "rumor_check"]


def test_web_researcher_has_a_single_tool_call_budget():
    assert RUMOR_WEB_RESEARCHER_CONFIG.max_tool_calls == 1
    assert RUMOR_WEB_RESEARCHER_CONFIG.max_turns == 3
