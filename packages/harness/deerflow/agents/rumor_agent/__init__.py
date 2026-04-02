"""Rumor Detection agent — DeerFlow-style orchestrating agent.

Registered as a LangGraph graph in ``langgraph.json``, on par with ``lead_agent``.
Uses ``create_agent`` with a full middleware chain, sub-agent delegation via
``task`` tool, and a fine-tuned classifier exposed as ``rumor_check`` tool.
"""

import logging

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.rumor_agent.prompt import build_rumor_system_prompt
from deerflow.agents.rumor_agent.tools import rumor_check_tool
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import get_app_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


def _resolve_model_name() -> str:
    """Resolve the default model name from config."""
    app_config = get_app_config()
    if not app_config.models:
        raise ValueError(
            "No chat models are configured. "
            "Please configure at least one model in config.yaml."
        )
    return app_config.models[0].name


def _build_middlewares():
    """Build the middleware chain for rumor_agent.

    Mirrors the lead_agent chain (ThreadData → Sandbox → Uploads → ToolError)
    plus rumor-specific additions (Title, Memory, SubagentLimit, LoopDetection).
    """
    middlewares = build_lead_runtime_middlewares(lazy_init=True)

    middlewares.append(TitleMiddleware())
    middlewares.append(MemoryMiddleware(agent_name="rumor"))
    middlewares.append(SubagentLimitMiddleware(max_concurrent=3))
    middlewares.append(LoopDetectionMiddleware())

    return middlewares


def make_rumor_agent(config: RunnableConfig):
    """Factory function referenced by ``langgraph.json``."""
    from deerflow.tools import get_available_tools

    model_name = _resolve_model_name()

    logger.info(
        "Creating rumor_agent (model=%s)",
        model_name,
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
        subagent_enabled=True,
    )
    tools = base_tools + [rumor_check_tool]

    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=True),
        tools=tools,
        middleware=_build_middlewares(),
        system_prompt=build_rumor_system_prompt(),
        state_schema=ThreadState,
    )
