"""Public fact-check API backed by the existing RumorBuster LangGraph agent."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from langgraph_sdk import get_client
from langgraph_sdk.errors import LangGraphError, NotFoundError
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.gateway.config import get_gateway_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/checks", tags=["checks"])


class CheckRequest(BaseModel):
    """Input accepted by the synchronous fact-check endpoint."""

    claim: str = Field(min_length=4, max_length=5000)
    source_url: AnyHttpUrl | None = None

    @field_validator("claim")
    @classmethod
    def normalize_claim(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 4:
            raise ValueError("claim must contain at least 4 non-whitespace characters")
        return value

    @field_validator("source_url")
    @classmethod
    def require_public_http_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return value
        host = (value.host or "").rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("source_url must reference a public HTTP(S) host")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return value
        if not address.is_global:
            raise ValueError("source_url must reference a public HTTP(S) host")
        return value


class CheckResponse(BaseModel):
    """Stable response shared by create and status endpoints."""

    check_id: str
    status: Literal["running", "completed", "needs_input", "degraded"]
    workflow: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] | None = None


def get_langgraph_client():
    """Construct a lightweight async SDK client for the internal server."""

    return get_client(url=get_gateway_config().langgraph_url)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _state_values(state: Any) -> dict[str, Any]:
    state_dict = _as_dict(state)
    values = state_dict.get("values")
    if isinstance(values, Mapping):
        return dict(values)
    return state_dict


def _response_from_values(check_id: str, values: Any) -> CheckResponse:
    values_dict = _as_dict(values)
    workflow = _as_dict(values_dict.get("rumor_workflow"))
    branch_status = values_dict.get("rumor_branch_status")
    if isinstance(branch_status, Mapping):
        workflow["branch_status"] = dict(branch_status)
    report_value = values_dict.get("rumor_report")
    report = _as_dict(report_value) if isinstance(report_value, Mapping) else None
    stage = str(workflow.get("stage") or "")
    degradation_codes = workflow.get("degradation_codes")

    if stage == "needs_input":
        status: Literal["running", "completed", "needs_input", "degraded"] = "needs_input"
    elif report is None:
        status = "running"
    elif isinstance(degradation_codes, list) and degradation_codes:
        status = "degraded"
    else:
        status = "completed"

    return CheckResponse(
        check_id=check_id,
        status=status,
        workflow=workflow,
        report=report,
    )


def _build_prompt(request: CheckRequest) -> str:
    prompt = f"请核验以下主张：\n{request.claim}"
    if request.source_url is not None:
        prompt += f"\n\n来源页面：{request.source_url}"
    return prompt


async def _resolve_assistant_id(client: Any) -> str:
    graph_id = get_gateway_config().rumor_agent_graph_id
    assistants = await client.assistants.search(graph_id=graph_id)
    if not assistants:
        raise RuntimeError(f"LangGraph graph '{graph_id}' is not available")
    assistant = assistants[0]
    if not isinstance(assistant, Mapping) or not assistant.get("assistant_id"):
        raise RuntimeError(f"LangGraph graph '{graph_id}' returned an invalid assistant")
    return str(assistant["assistant_id"])


@router.post("", response_model=CheckResponse, summary="Create a fact check")
async def create_check(request: CheckRequest) -> CheckResponse | JSONResponse:
    """Create a LangGraph thread and wait for the current RumorBuster run."""

    client = get_langgraph_client()
    try:
        assistant_id = await _resolve_assistant_id(client)
        thread = await client.threads.create()
        thread_id = str(thread["thread_id"])
    except (LangGraphError, OSError, RuntimeError, KeyError, TypeError) as exc:
        logger.warning("Unable to initialize fact check: %s", exc)
        raise HTTPException(status_code=503, detail="LangGraph service is unavailable") from exc

    timeout = get_gateway_config().rumor_check_timeout_seconds
    try:
        result = await asyncio.wait_for(
            client.runs.wait(
                thread_id,
                assistant_id,
                input={"messages": [{"role": "human", "content": _build_prompt(request)}]},
                config={"recursion_limit": 100},
                on_disconnect="continue",
            ),
            timeout=timeout,
        )
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={
                "check_id": thread_id,
                "status": "running",
                "workflow": {},
                "report": None,
                "detail": f"Fact check exceeded the {timeout:g}-second wait limit; query the check_id later",
            },
        )
    except (LangGraphError, OSError) as exc:
        logger.warning("Fact check run failed for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=503, detail="LangGraph service is unavailable") from exc

    return _response_from_values(thread_id, result)


@router.get("/{check_id}", response_model=CheckResponse, summary="Get a fact check")
async def get_check(check_id: str) -> CheckResponse:
    """Read the latest deterministic workflow and report from thread state."""

    try:
        uuid.UUID(check_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Fact check not found") from exc

    try:
        state = await get_langgraph_client().threads.get_state(check_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Fact check not found") from exc
    except (LangGraphError, OSError) as exc:
        logger.warning("Unable to read fact check %s: %s", check_id, exc)
        raise HTTPException(status_code=503, detail="LangGraph service is unavailable") from exc
    if not state:
        raise HTTPException(status_code=404, detail="Fact check not found")
    return _response_from_values(check_id, _state_values(state))


async def check_langgraph_ready() -> dict[str, str]:
    """Verify the graph registry without invoking an external model."""

    client = get_langgraph_client()
    try:
        await _resolve_assistant_id(client)
    except (LangGraphError, OSError, RuntimeError, KeyError, TypeError) as exc:
        logger.warning("LangGraph readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail="LangGraph service is unavailable") from exc
    return {"status": "ready", "service": "rumor-buster-gateway", "langgraph": "ready"}
