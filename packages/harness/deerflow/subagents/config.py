"""Subagent configuration definitions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubagentConfig:
    """Configuration for a subagent.

    Attributes:
        name: Unique identifier for the subagent.
        description: When Claude should delegate to this subagent.
        system_prompt: The system prompt that guides the subagent's behavior.
        tools: Optional list of tool names to allow. If None, inherits all tools.
        disallowed_tools: Optional list of tool names to deny.
        model: Model to use - 'inherit' uses parent's model.
        max_turns: Maximum number of agent turns before stopping.
        max_tool_calls: Optional maximum number of tool calls in one run.
        direct_tool: Optional tool to invoke without an intermediate model pass.
        direct_tool_input_builder: Converts the delegated task into direct tool input.
        timeout_seconds: Maximum execution time in seconds (default: 900 = 15 minutes).
    """

    name: str
    description: str
    system_prompt: str
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
    model: str = "inherit"
    max_turns: int = 50
    max_tool_calls: int | None = None
    direct_tool: str | None = None
    direct_tool_input_builder: Callable[[str], dict[str, Any]] | None = None
    timeout_seconds: int = 900
