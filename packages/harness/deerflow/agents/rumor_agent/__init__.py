"""RumorBuster fact-checking agent registered in ``langgraph.json``.

Optional search and classifier tools are exposed only when their corresponding
services are explicitly configured.
"""

import logging
import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.runnables import RunnableConfig

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.rumor_evidence_policy_middleware import (
    RumorEvidencePolicyMiddleware,
)
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.rumor_agent.claim_router import classify_checkability_tool
from deerflow.agents.rumor_agent.evidence import assess_evidence_tool
from deerflow.agents.rumor_agent.prompt import build_rumor_system_prompt
from deerflow.agents.rumor_agent.rag import retrieve_verified_rumors_tool
from deerflow.agents.rumor_agent.tools import rumor_check_tool
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import get_app_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


def _resolve_model_name() -> str:
    """Resolve the default model name from config."""
    app_config = get_app_config()
    if not app_config.models:
        raise ValueError("No chat models are configured. Please configure at least one model in config.yaml.")
    return app_config.models[0].name


def _build_middlewares(
    *,
    web_search_enabled: bool,
    web_fetch_enabled: bool,
    classifier_enabled: bool,
):
    """Build the middleware chain for rumor_agent.

    Mirrors the lead_agent chain (ThreadData → Sandbox → Uploads → ToolError)
    plus rumor-specific additions (Title, Memory, SubagentLimit, LoopDetection).
    """
    from deerflow.agents.middlewares.rumor_workflow_middleware import RumorWorkflowMiddleware

    middlewares = build_lead_runtime_middlewares(lazy_init=True)

    middlewares.append(TitleMiddleware())
    middlewares.append(MemoryMiddleware(agent_name="rumor"))
    middlewares.append(SubagentLimitMiddleware(max_concurrent=1))
    middlewares.append(
        RumorWorkflowMiddleware(
            web_search_enabled=web_search_enabled,
            web_fetch_enabled=web_fetch_enabled,
            classifier_enabled=classifier_enabled,
        )
    )
    middlewares.append(
        ToolCallLimitMiddleware(
            tool_name="task",
            run_limit=1,
            exit_behavior="continue",
        )
    )
    middlewares.append(
        ToolCallLimitMiddleware(
            tool_name="rumor_check",
            run_limit=1,
            exit_behavior="continue",
        )
    )
    middlewares.append(
        ToolCallLimitMiddleware(
            tool_name="web_fetch",
            run_limit=1,
            exit_behavior="continue",
        )
    )
    for tool_name in (
        "classify_checkability",
        "retrieve_verified_rumors",
        "assess_evidence",
    ):
        middlewares.append(
            ToolCallLimitMiddleware(
                tool_name=tool_name,
                run_limit=1,
                exit_behavior="continue",
            )
        )
    middlewares.append(
        ModelCallLimitMiddleware(
            run_limit=10,
            exit_behavior="end",
        )
    )
    middlewares.append(LoopDetectionMiddleware(warn_threshold=2, hard_limit=3))
    middlewares.append(RumorEvidencePolicyMiddleware())

    return middlewares


def _select_main_agent_tools(
    base_tools,
    *,
    classifier_enabled: bool,
    web_fetch_enabled: bool,
):
    """Keep search delegated while allowing one configured source-page fetch."""
    tools = [tool for tool in base_tools if tool.name != "web_search" and (web_fetch_enabled or tool.name != "web_fetch")]
    if classifier_enabled and all(tool.name != "rumor_check" for tool in tools):
        tools.append(rumor_check_tool)
    for domain_tool in (
        classify_checkability_tool,
        retrieve_verified_rumors_tool,
        assess_evidence_tool,
    ):
        if all(tool.name != domain_tool.name for tool in tools):
            tools.append(domain_tool)
    return tools


def make_rumor_agent_v2(config: RunnableConfig):
    """Build the preserved V2 create_agent workflow for rollback and comparison."""
    from deerflow.tools import get_available_tools

    app_config = get_app_config()
    model_name = _resolve_model_name()
    configured_tool_names = {tool.name for tool in app_config.tools}
    web_search_enabled = "web_search" in configured_tool_names
    web_fetch_enabled = "web_fetch" in configured_tool_names
    classifier_enabled = bool(os.getenv("RUMOR_MODEL_BASE_URL", "").strip())

    logger.info(
        "Creating rumor_agent (model=%s, web_search=%s, web_fetch=%s, classifier=%s)",
        model_name,
        web_search_enabled,
        web_fetch_enabled,
        classifier_enabled,
    )

    if "metadata" not in config:
        config["metadata"] = {}
    config["metadata"].update(
        {
            "agent_name": "rumor",
            "model_name": model_name,
        }
    )

    base_tools = get_available_tools(
        model_name=model_name,
        subagent_enabled=web_search_enabled,
    )
    tools = _select_main_agent_tools(
        base_tools,
        classifier_enabled=classifier_enabled,
        web_fetch_enabled=web_fetch_enabled,
    )

    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=True),
        tools=tools,
        middleware=_build_middlewares(
            web_search_enabled=web_search_enabled,
            web_fetch_enabled=web_fetch_enabled,
            classifier_enabled=classifier_enabled,
        ),
        system_prompt=build_rumor_system_prompt(
            web_search_enabled=web_search_enabled,
            web_fetch_enabled=web_fetch_enabled,
            classifier_enabled=classifier_enabled,
        ),
        state_schema=ThreadState,
    )


def make_rumor_agent(config: RunnableConfig):
    """Build the default explicit RumorBuster V3 StateGraph."""
    from deerflow.agents.rumor_agent.graph_v3 import build_rumor_graph_v3, make_default_v3_services

    return build_rumor_graph_v3(make_default_v3_services())


__all__ = [
    "make_rumor_agent",
    "make_rumor_agent_v2",
]
