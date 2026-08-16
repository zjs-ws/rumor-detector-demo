"""Deterministic stage gate for the RumorBuster create_agent loop."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.rumor_agent.evidence import decide_evidence, observed_evidence_urls
from deerflow.agents.rumor_agent.schemas import (
    Checkability,
    ClaimContext,
    EvidenceItem,
    ResearchResult,
)
from deerflow.agents.rumor_agent.source_policy import normalize_evidence_items
from deerflow.agents.rumor_agent.timeline import build_timeline

_URL_RE = re.compile(r"https?://[^\s\]<>\)\"']+")
_VERIFY_INTENT_RE = re.compile(r"(?:核验|查证|真假|谣言|可信|是否属实|是真的吗|分析.*网页|读取.*网页)")
_TASK_PREFIX = "Task Succeeded. Result:"
_STAGE_TOOL = {
    "fetch_original": "web_fetch",
    "checkability": "classify_checkability",
    "rag": "retrieve_verified_rumors",
    "research": "task",
    "classifier": "rumor_check",
    "adjudicate": "assess_evidence",
}


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content) if content else ""


def _latest_run(messages: list[Any]) -> tuple[object | None, list[Any]]:
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "type", None) == "human":
            return messages[index], messages[index:]
    return None, []


_EXPECTED_TOP_LEVEL_KEYS = ("evidence", "rejected_evidence", "notes", "observed_urls", "fetched_urls", "status")
_FENCED_CODE_RE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


def _json_object(text: str, required_keys: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Extract a strict JSON object from subagent text.

    Models occasionally wrap the payload in markdown fences or prefix it with
    prose.  When ``required_keys`` is given, a decode candidate is accepted
    only if the dict carries at least one of those keys, so a stray JSON
    fragment in surrounding text can never be mistaken for the result.
    """
    value = text.strip()
    if value.startswith(_TASK_PREFIX):
        value = value[len(_TASK_PREFIX) :].strip()
    fenced = _FENCED_CODE_RE.match(value)
    if fenced:
        value = fenced.group(1).strip()
    for start in (match.start() for match in re.finditer(r"[{\[]", value)):
        try:
            payload, _ = json.JSONDecoder().raw_decode(value[start:])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and (not required_keys or any(key in payload for key in required_keys)):
            return payload
    return None


def parse_research_result(text: str) -> tuple[ResearchResult, list[dict[str, str]]]:
    """Parse a subagent JSON result without asking the main model to copy it."""
    payload = _json_object(text, required_keys=_EXPECTED_TOP_LEVEL_KEYS)
    if payload is None:
        return ResearchResult(status="unavailable", notes="研究结果不是合法JSON"), [{"reason_code": "invalid_research_json", "explanation": "研究子Agent未返回合法JSON对象"}]

    valid: list[EvidenceItem] = []
    rejected: list[dict[str, str]] = []
    for raw_rejection in payload.get("rejected_evidence", []):
        if isinstance(raw_rejection, dict) and raw_rejection.get("reason_code"):
            rejected.append({key: str(value) for key, value in raw_rejection.items()})
    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raw_evidence = []
        rejected.append({"reason_code": "invalid_evidence_list", "explanation": "evidence字段不是数组"})
    for index, raw in enumerate(raw_evidence):
        candidate = raw

        # Research subagents occasionally return fetch_attempts as a list of
        # URL strings, while EvidenceItem requires list[dict].
        #
        # Normalize this model-generated field before strict Pydantic validation.
        # The values here are only temporary provenance hints; graph_v3 later
        # replaces them with provenance derived from the actual web_fetch
        # ToolMessages.
        if isinstance(raw, dict):
            candidate = dict(raw)
            attempts = candidate.get("fetch_attempts")

            if isinstance(attempts, list):
                normalized_attempts: list[dict[str, Any]] = []

                for attempt in attempts:
                    if isinstance(attempt, dict):
                        normalized_attempts.append(attempt)
                    elif isinstance(attempt, str) and attempt.strip():
                        normalized_attempts.append(
                            {
                                "url": attempt.strip(),
                                "final_url": None,
                                "status": "reported_by_model",
                            }
                        )

                candidate["fetch_attempts"] = normalized_attempts

            elif attempts is None:
                candidate["fetch_attempts"] = []

            else:
                # Invalid non-list model output should not make an otherwise
                # usable evidence item fail before verified provenance is applied.
                candidate["fetch_attempts"] = []

        try:
            valid.append(EvidenceItem.model_validate(candidate))
        except Exception as exc:
            rejected.append(
                {
                    "evidence_id": (
                        raw.get("id", f"invalid-{index + 1}")
                        if isinstance(raw, dict)
                        else f"invalid-{index + 1}"
                    ),
                    "reason_code": "invalid_schema",
                    "explanation": f"证据字段非法：{exc}",
                }
            )
    status = str(payload.get("status", "ok" if valid else "insufficient"))
    notes = str(payload.get("notes", ""))
    return ResearchResult(status=status, evidence=valid, notes=notes), rejected


def _normalize_task_message(result: Any) -> Any:
    """Replace free-form researcher output with one canonical JSON ToolMessage."""
    if not isinstance(result, ToolMessage):
        return result
    research, rejected = parse_research_result(_message_text(result))
    status = research.status if research.status in {"ok", "insufficient", "unavailable"} else "unavailable"
    payload = research.model_copy(update={"status": status}).model_dump(mode="json")
    payload["rejected_evidence"] = rejected
    return result.model_copy(update={"content": json.dumps(payload, ensure_ascii=False)})


def _tool_results(messages: list[Any]) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for message in messages:
        if getattr(message, "type", None) != "tool":
            continue
        name = getattr(message, "name", "")
        if name:
            results.setdefault(name, []).append(_message_text(message))
    return results


def _claim_candidate(raw_input: str) -> str:
    without_urls = _URL_RE.sub("", raw_input)
    lines = [line.strip() for line in without_urls.splitlines() if line.strip() and not line.strip().startswith(("来源页面：", "来源页面:"))]
    value = " ".join(lines)
    value = re.sub(r"^(?:请)?(?:帮我)?(?:读取并)?(?:核验|查证|分析)(?:以下)?(?:网页内容|说法|言论)?[：:\s]*", "", value)
    value = " ".join(value.split()).strip()
    if re.fullmatch(r"(?:这个|该|以下)?网页(?:的)?(?:主要)?(?:内容)?[：:]?", value):
        return ""
    return value[:1000]


def _fallback_page_claim(fetch_payload: dict[str, Any] | None) -> str:
    if not fetch_payload:
        return ""
    title = str(fetch_payload.get("title", "")).strip()
    content = str(fetch_payload.get("content", "")).strip()
    return " ".join(f"{title} {content[:600]}".split()).strip()


def _parse_payload(results: dict[str, list[str]], name: str) -> dict[str, Any] | None:
    values = results.get(name) or []
    return _json_object(values[-1]) if values else None


def derive_workflow(
    state: AgentState,
    *,
    web_search_enabled: bool,
    web_fetch_enabled: bool,
    classifier_enabled: bool,
) -> dict[str, Any]:
    """Derive the current stage solely from the latest user turn and tool results."""
    messages = list(state.get("messages", []))
    human, current = _latest_run(messages)
    raw_input = _message_text(human) if human is not None else ""
    input_message_id = getattr(human, "id", None)
    urls = _URL_RE.findall(raw_input)
    source_url = urls[0].rstrip(".,;:!?，。；：！？") if urls else None
    initial_claim = _claim_candidate(raw_input)
    is_verification = bool(source_url or _VERIFY_INTENT_RE.search(raw_input))
    results = _tool_results(current)
    degradations: list[str] = []

    fetch_payload = _parse_payload(results, "web_fetch")
    fetch_attempted = "web_fetch" in results
    fetch_ok = bool(fetch_payload and fetch_payload.get("content"))
    if fetch_attempted and not fetch_ok:
        degradations.append("original_fetch_unavailable")

    checkability_attempted = "classify_checkability" in results
    checkability_payload = _parse_payload(results, "classify_checkability")
    if checkability_attempted and not checkability_payload:
        degradations.append("checkability_unavailable")
        checkability_payload = {
            "claim": initial_claim,
            "claim_type": "unclear",
            "checkability": Checkability.NEEDS_CLARIFICATION.value,
            "reason": "可核验性工具未返回合法结果，请补充一条明确、可公开验证的事实主张。",
        }
    claim_context = checkability_payload.get("claim_context") if checkability_payload else None
    normalized_claim = str(claim_context.get("normalized_claim", "")) if isinstance(claim_context, dict) else initial_claim
    if not normalized_claim and fetch_ok:
        normalized_claim = _fallback_page_claim(fetch_payload)

    rag_attempted = "retrieve_verified_rumors" in results
    rag_payload = _parse_payload(results, "retrieve_verified_rumors")
    if rag_attempted and not rag_payload:
        degradations.append("rag_unavailable")
        rag_payload = {
            "status": "unavailable",
            "query": normalized_claim,
            "matches": [],
            "threshold": 0.0,
            "authoritative": False,
            "note": "RAG 本轮不可用；历史召回不会影响证据裁决。",
        }

    classifier_attempted = "rumor_check" in results
    classifier_payload = _parse_payload(results, "rumor_check")
    if classifier_enabled and classifier_attempted and not classifier_payload:
        degradations.append("classifier_unavailable")
        classifier_payload = {
            "status": "unavailable",
            "role": "auxiliary_signal",
            "label": "uncertain",
            "rationale": "分类器未返回合法结果。",
            "authoritative": False,
        }

    research = ResearchResult(status="unavailable")
    research_rejected: list[dict[str, str]] = []
    if "task" in results:
        research, research_rejected = parse_research_result(results["task"][-1])
        if research.status not in {"ok", "insufficient"}:
            degradations.append("research_unavailable")
    normalized_evidence, _ = normalize_evidence_items(
        research.evidence,
        None if claim_context is None else ClaimContext.model_validate(claim_context),
    )

    decision_attempted = "assess_evidence" in results
    decision_payload = _parse_payload(results, "assess_evidence")
    if decision_attempted and not decision_payload:
        degradations.append("adjudicator_tool_unavailable")
        decision_payload = decide_evidence(
            evidence=normalized_evidence,
            classifier_signal=classifier_payload,
            allowed_urls=observed_evidence_urls(current),
            original_url=source_url,
            claim_context=claim_context,
        ).model_dump(mode="json")
    timeline = None
    if decision_payload:
        timeline = build_timeline(
            evidence=normalized_evidence,
            decision=decision_payload,
            rag_result=rag_payload,
        ).model_dump(mode="json")

    if not is_verification:
        stage = "conversation"
    elif source_url and not initial_claim and web_fetch_enabled and not fetch_attempted:
        stage = "fetch_original"
    elif source_url and not initial_claim and fetch_attempted and not fetch_ok:
        stage = "needs_input"
        checkability_payload = {
            "claim": "",
            "claim_type": "unclear",
            "checkability": Checkability.NEEDS_CLARIFICATION.value,
            "reason": "网页抓取失败且用户没有提供独立的文字主张。",
        }
    elif not checkability_payload:
        stage = "checkability"
    elif checkability_payload.get("checkability") != Checkability.CHECKABLE_NOW.value:
        stage = "report"
    elif source_url and web_fetch_enabled and not fetch_attempted:
        stage = "fetch_original"
    elif not rag_attempted:
        stage = "rag"
    elif web_search_enabled and "task" not in results:
        stage = "research"
    elif classifier_enabled and not classifier_attempted:
        stage = "classifier"
    elif not decision_attempted:
        stage = "adjudicate"
    else:
        stage = "report"

    trace = []
    degraded_tools = {
        "web_fetch": "original_fetch_unavailable",
        "classify_checkability": "checkability_unavailable",
        "retrieve_verified_rumors": "rag_unavailable",
        "task": "research_unavailable",
        "rumor_check": "classifier_unavailable",
        "assess_evidence": "adjudicator_tool_unavailable",
    }
    for tool_name in (
        "web_fetch",
        "classify_checkability",
        "retrieve_verified_rumors",
        "task",
        "rumor_check",
        "assess_evidence",
    ):
        if tool_name in results:
            status = "degraded" if degraded_tools[tool_name] in degradations else "completed"
            trace.append({"tool": tool_name, "status": status, "calls": len(results[tool_name])})

    return {
        "input_message_id": input_message_id,
        "stage": stage,
        "raw_input": raw_input,
        "source_url": source_url,
        "claim_context": claim_context,
        "normalized_claim": normalized_claim,
        "checkability": checkability_payload,
        "original_page": fetch_payload,
        "rag_result": rag_payload,
        "research_result": research.model_dump(mode="json"),
        "research_rejected": research_rejected,
        "classifier_signal": classifier_payload,
        "evidence": [item.model_dump(mode="json") for item in normalized_evidence],
        "decision": decision_payload,
        "timeline": timeline,
        "degradation_codes": list(dict.fromkeys(degradations)),
        "trace": trace,
        "capabilities": {
            "web_search": web_search_enabled,
            "web_fetch": web_fetch_enabled,
            "classifier": classifier_enabled,
            "rag": True,
        },
    }


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or tool.get("function", {}).get("name") or "")
    return str(getattr(tool, "name", ""))


class RumorWorkflowMiddleware(AgentMiddleware[AgentState]):
    """Gate each verification stage while preserving DeerFlow's agent runtime."""

    def __init__(self, *, web_search_enabled: bool, web_fetch_enabled: bool, classifier_enabled: bool):
        self.web_search_enabled = web_search_enabled
        self.web_fetch_enabled = web_fetch_enabled
        self.classifier_enabled = classifier_enabled

    def _derive(self, state: AgentState) -> dict[str, Any]:
        return derive_workflow(
            state,
            web_search_enabled=self.web_search_enabled,
            web_fetch_enabled=self.web_fetch_enabled,
            classifier_enabled=self.classifier_enabled,
        )

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any]:
        workflow = self._derive(state)
        update: dict[str, Any] = {"rumor_workflow": workflow}
        old = state.get("rumor_workflow") or {}
        if old.get("input_message_id") != workflow.get("input_message_id"):
            update["rumor_report"] = None
        return update

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any]:
        return self.before_model(state, runtime)

    def _model_request(self, request: ModelRequest) -> ModelRequest:
        workflow = self._derive(request.state)
        expected = _STAGE_TOOL.get(workflow["stage"])
        if not expected:
            return request.override(tools=[], tool_choice=None)
        tools = [tool for tool in request.tools if _tool_name(tool) == expected]
        stage_prompt = f"\n\n<workflow_gate>当前唯一阶段：{workflow['stage']}。必须调用且只调用工具 {expected}；不得直接输出最终结论。</workflow_gate>"
        system_text = (request.system_prompt or "") + stage_prompt
        return request.override(
            tools=tools,
            # DeepSeek thinking mode rejects API-level forced tool_choice. The
            # post-model gate below deterministically replaces missing or
            # incorrect calls, while this request exposes only the one legal tool.
            tool_choice=None,
            system_message=SystemMessage(content=system_text),
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._model_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._model_request(request))

    def _locked_args(self, state: AgentState, tool_name: str, incoming: dict[str, Any]) -> dict[str, Any]:
        workflow = self._derive(state)
        claim = workflow.get("normalized_claim") or _claim_candidate(workflow.get("raw_input", ""))
        if tool_name == "web_fetch":
            return {"url": workflow.get("source_url")}
        if tool_name == "retrieve_verified_rumors":
            return {"claim": claim, "top_k": 3, "threshold": 0.05}
        if tool_name == "rumor_check":
            return {"claim": claim}
        if tool_name == "task":
            subclaims = (workflow.get("claim_context") or {}).get("subclaims", [])
            subclaim_text = "\n".join(f"- {item.get('id')}: {item.get('text')}" for item in subclaims)
            return {
                "description": "核验公开来源",
                "prompt": (f"待核验原文：{claim}\n子主张：\n{subclaim_text or '- claim-1: ' + claim}\n返回严格JSON证据；每条证据必须关联claim_ids，不得输出最终真假。"),
                "subagent_type": "web-researcher",
                "max_turns": 7,
            }
        if tool_name == "assess_evidence":
            return {
                "evidence": workflow.get("evidence", []),
                "classifier_signal": workflow.get("classifier_signal"),
                "original_url": workflow.get("source_url"),
                "claim_context": workflow.get("claim_context"),
            }
        if tool_name == "classify_checkability":
            proposed = str(incoming.get("claim", "")).strip()[:1000]
            if len(proposed) < 4:
                proposed = claim or _fallback_page_claim(workflow.get("original_page"))
            subclaims = incoming.get("subclaims")
            if not isinstance(subclaims, list):
                subclaims = [{"id": "claim-1", "text": proposed, "material": True}]
            return {
                "claim": proposed,
                "subclaims": subclaims[:3],
                "temporality": incoming.get("temporality", "unknown"),
                "event_date": incoming.get("event_date"),
                "source_url": workflow.get("source_url"),
            }
        return incoming

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        call = dict(request.tool_call)
        call["args"] = self._locked_args(request.state, call.get("name", ""), call.get("args", {}))
        result = handler(request.override(tool_call=call))
        return _normalize_task_message(result) if call.get("name") == "task" else result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        call = dict(request.tool_call)
        call["args"] = self._locked_args(request.state, call.get("name", ""), call.get("args", {}))
        result = await handler(request.override(tool_call=call))
        return _normalize_task_message(result) if call.get("name") == "task" else result

    def _after_model(self, state: AgentState) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            return None
        workflow = self._derive(state)
        expected = _STAGE_TOOL.get(workflow["stage"])
        if not expected:
            return None
        calls = getattr(last, "tool_calls", []) or []
        if len(calls) == 1 and calls[0].get("name") == expected:
            locked_args = self._locked_args(state, expected, calls[0].get("args", {}))
            if calls[0].get("args", {}) == locked_args:
                return None
            corrected_call = dict(calls[0])
            corrected_call["args"] = locked_args
        else:
            corrected_call = {
                "id": f"rumor-{workflow['stage']}-{uuid.uuid4().hex[:8]}",
                "name": expected,
                "args": self._locked_args(state, expected, {}),
                "type": "tool_call",
            }
        corrected = last.model_copy(update={"content": "", "tool_calls": [corrected_call]})
        return {"messages": [corrected]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._after_model(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._after_model(state)


__all__ = ["RumorWorkflowMiddleware", "derive_workflow", "parse_research_result"]
