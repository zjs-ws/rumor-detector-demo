"""Final provenance guard and structured-state projector for RumorBuster.

The model prompt asks for traceable citations, but provenance and confidence
must not depend on prompt compliance alone. This middleware validates the final
URL report against tool messages from the current run.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import override
from urllib.parse import unquote, urlsplit, urlunsplit

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_PLAIN_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+")
_VERDICT_PATTERN = re.compile(r"(?m)^\*\*判定结论\*\*[：:].*$")
_STRENGTH_PATTERN = re.compile(r"(?m)^\*\*证据强度\*\*[：:].*$")
_POLICY_NOTE = "> **证据策略校正**：最终结论已按确定性规则结果校正，通用模型无权覆盖该结果。"


@dataclass(frozen=True)
class _FetchedPage:
    url: str
    title: str


def _normalize_url(value: str) -> str:
    """Normalize equivalent display encodings for provenance comparison."""
    parsed = urlsplit(value.rstrip(".,;:!?，。；：！？"))
    path = unquote(parsed.path)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def _message_text(message: object) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content) if content else ""


def _tool_name(message: object) -> str:
    name = getattr(message, "name", None)
    if isinstance(name, str):
        return name
    return ""


def _extract_urls(text: str) -> set[str]:
    return {normalized for raw_url in _PLAIN_URL_PATTERN.findall(text) if (normalized := _normalize_url(raw_url))}


def _parse_fetched_page(content: str) -> _FetchedPage | None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_url = payload.get("source_url") or payload.get("requested_url")
    if not isinstance(raw_url, str) or not raw_url.startswith(("http://", "https://")):
        return None
    raw_title = payload.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    return _FetchedPage(url=raw_url, title=title or "待核验原网页")


def _safe_decision(workflow: dict) -> dict:
    checkability = (workflow.get("checkability") or {}).get("checkability")
    mapping = {
        "checkable_later": "暂不可核验",
        "not_publicly_checkable": "不可公开核验",
        "not_a_factual_claim": "非事实性表达",
        "needs_clarification": "需要补充主张",
    }
    verdict = mapping.get(checkability, "证据不足")
    return {
        "verdict": verdict,
        "strength": "not_applicable" if checkability and checkability != "checkable_now" else "insufficient",
        "accepted_evidence_ids": [],
        "excluded_evidence": workflow.get("research_rejected", []),
        "reason_codes": [checkability or "workflow_incomplete"],
        "classifier_consistency": "not_comparable",
        "explanation": (workflow.get("checkability") or {}).get("reason", "本轮未取得规则裁决结果。"),
        "subclaim_decisions": {},
    }


def _structured_report(workflow: dict) -> dict:
    original = workflow.get("original_page")
    if isinstance(original, dict):
        original = {key: original.get(key) for key in ("source_url", "requested_url", "title", "content_chars", "truncated")}
    decision = workflow.get("decision") or _safe_decision(workflow)
    timeline = workflow.get("timeline") or {
        "timeline_status": "insufficient",
        "events": [],
        "note": "没有足够的带日期可追溯事件。",
    }
    return {
        "schema_version": "rumorbuster-report-v2",
        "claim": workflow.get("claim_context") or {"normalized_claim": workflow.get("normalized_claim", ""), "subclaims": []},
        "checkability": workflow.get("checkability"),
        "capabilities": workflow.get("capabilities", {}),
        "original_page": original,
        "rag": workflow.get("rag_result"),
        "classifier_signal": workflow.get("classifier_signal"),
        "evidence": workflow.get("evidence", []),
        "decision": decision,
        "timeline": timeline,
        "limitations": workflow.get("degradation_codes", []),
        "workflow_trace": workflow.get("trace", []),
    }


def _render_deterministic_report(report: dict) -> str:
    decision = report["decision"]
    claim = report.get("claim") or {}
    claim_text = claim.get("normalized_claim", "") if isinstance(claim, dict) else str(claim)
    checkability = report.get("checkability") or {}
    lines = [
        "## 谣言检测报告",
        "",
        f"**待检测言论**：{claim_text or '未提取到明确主张'}",
        "",
        f"**可核验状态**：{checkability.get('checkability', 'unknown')}",
        "",
        f"**判定结论**：{decision.get('verdict', '证据不足')}",
        f"**证据强度**：{decision.get('strength', 'insufficient')}",
        "",
        _POLICY_NOTE,
        "",
        "### 外部证据核验",
    ]
    evidence = report.get("evidence") or []
    if evidence:
        accepted = set(decision.get("accepted_evidence_ids", []))
        for item in evidence:
            marker = "用于裁决" if item.get("id") in accepted else "未用于裁决"
            lines.append(f"- [{item.get('title', '来源')}]({item.get('url', '')}) — {item.get('verified_source_level') or item.get('source_level', 'D')}级，{marker}：{item.get('summary', '')}")
    else:
        lines.append("本轮没有通过结构校验的外部证据。")
    lines.extend(["", "### RAG 历史命中"])
    matches = (report.get("rag") or {}).get("matches", [])
    lines.extend([f"- {item.get('canonical_claim')}（相似度 {item.get('similarity', 0):.2f}）" for item in matches] or ["未命中；不会因此推断真假。"])
    lines.extend(["", "### 综合分析", decision.get("explanation", "")])
    lines.extend(["", "### 来源"])
    original = report.get("original_page") or {}
    if original.get("source_url"):
        lines.append(f"- [{original.get('title') or '待核验原网页'}]({original['source_url']}) — 待核验原网页（非独立证据）")
    lines.extend(f"- [{item.get('title', '来源')}]({item.get('url', '')}) — {item.get('summary', '')}" for item in evidence if item.get("url"))
    if len(lines) > 0 and lines[-1] == "### 来源":
        lines.append("本轮未获得可引用来源。")
    return "\n".join(lines)


class RumorEvidencePolicyMiddleware(AgentMiddleware[AgentState]):
    """Enforce URL provenance and conservative verdicts on final reports."""

    def _apply(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_message = messages[-1]
        if getattr(last_message, "type", None) != "ai":
            return None
        if getattr(last_message, "tool_calls", None):
            return None

        original_content = _message_text(last_message)
        content = original_content
        workflow = state.get("rumor_workflow") or {}
        workflow_report = None
        if workflow.get("stage") in {"report", "needs_input"}:
            workflow_report = _structured_report(workflow)
            if "## 谣言检测报告" not in content:
                content = _render_deterministic_report(workflow_report)
        if "## 谣言检测报告" not in content:
            return None

        fetched_pages: list[_FetchedPage] = []
        search_urls: set[str] = set()
        retrieved_urls: set[str] = set()
        tool_payloads: dict[str, dict] = {}
        assess_args: dict = {}
        for message in messages[:-1]:
            if getattr(message, "type", None) != "tool":
                continue
            tool_name = _tool_name(message)
            tool_content = _message_text(message)
            if tool_name == "web_fetch":
                page = _parse_fetched_page(tool_content)
                if page is not None:
                    fetched_pages.append(page)
            elif tool_name == "task":
                search_urls.update(_extract_urls(tool_content))
            elif tool_name == "retrieve_verified_rumors":
                retrieved_urls.update(_extract_urls(tool_content))
            if tool_name in {
                "classify_checkability",
                "retrieve_verified_rumors",
                "rumor_check",
                "assess_evidence",
            }:
                try:
                    payload = json.loads(tool_content)
                except (json.JSONDecodeError, TypeError):
                    payload = None
                if isinstance(payload, dict):
                    tool_payloads[tool_name] = payload

        for message in messages[:-1]:
            if getattr(message, "type", None) != "ai":
                continue
            for tool_call in getattr(message, "tool_calls", []) or []:
                if tool_call.get("name") == "assess_evidence" and isinstance(tool_call.get("args"), dict):
                    assess_args = tool_call["args"]

        original_urls = {_normalize_url(page.url) for page in fetched_pages}
        independent_urls = search_urls - original_urls
        allowed_urls = original_urls | search_urls | retrieved_urls
        changed = False

        def remove_untraceable_link(match: re.Match[str]) -> str:
            nonlocal changed
            label, url = match.groups()
            if _normalize_url(url) in allowed_urls:
                return match.group(0)
            changed = True
            logger.warning("Removed untraceable URL from rumor report: %s", url)
            return f"{label}（未验证链接已移除）"

        corrected = _MARKDOWN_LINK_PATTERN.sub(remove_untraceable_link, content)

        cited_urls = {_normalize_url(url) for _, url in _MARKDOWN_LINK_PATTERN.findall(corrected)}
        cited_independent_urls = cited_urls & independent_urls
        # The original page must remain visible as the primary, explicitly
        # non-independent source even if the model omitted it.
        missing_pages = [page for page in fetched_pages if _normalize_url(page.url) not in cited_urls]
        if missing_pages:
            if "### 来源" not in corrected:
                corrected = corrected.rstrip() + "\n\n### 来源\n"
            for page in missing_pages:
                corrected = corrected.rstrip() + f"\n- [{page.title}]({page.url}) — 待核验原网页（非独立证据）\n"
            changed = True

        decision = (workflow_report or {}).get("decision") or tool_payloads.get("assess_evidence")
        domain_workflow_started = bool({"classify_checkability", "retrieve_verified_rumors"} & tool_payloads.keys())
        if decision is not None:
            binding_verdict = str(decision.get("verdict", "证据不足"))
            binding_strength = str(decision.get("strength", "insufficient"))
            corrected_verdict = f"**判定结论**：{binding_verdict}"
            corrected_strength = f"**证据强度**：{binding_strength}"

            if _VERDICT_PATTERN.search(corrected):
                corrected = _VERDICT_PATTERN.sub(corrected_verdict, corrected)
            else:
                corrected = corrected.replace(
                    "## 谣言检测报告",
                    f"## 谣言检测报告\n\n{corrected_verdict}",
                    1,
                )

            if _STRENGTH_PATTERN.search(corrected):
                corrected = _STRENGTH_PATTERN.sub(corrected_strength, corrected)
            else:
                corrected = corrected.replace(
                    corrected_verdict,
                    f"{corrected_verdict}\n{corrected_strength}",
                    1,
                )

            if _POLICY_NOTE not in corrected:
                corrected = corrected.replace(
                    corrected_strength,
                    f"{corrected_strength}\n\n{_POLICY_NOTE}",
                    1,
                )
            changed = True
            logger.info("Bound final report to deterministic evidence decision: %s", binding_verdict)
        elif domain_workflow_started:
            corrected_verdict = "**判定结论**：证据不足"
            corrected_strength = "**证据强度**：insufficient"
            corrected = _VERDICT_PATTERN.sub(corrected_verdict, corrected)
            corrected = _STRENGTH_PATTERN.sub(corrected_strength, corrected)
            corrected = corrected.replace(
                corrected_strength,
                f"{corrected_strength}\n\n> **证据策略校正**：本轮未取得规则裁决结果，已安全降级。",
                1,
            )
            changed = True
        elif fetched_pages and not cited_independent_urls:
            legacy_verdict = "**判定结论**：存疑（证据不足，未获得独立外部来源）"
            legacy_strength = "**证据强度**：低"
            corrected = _VERDICT_PATTERN.sub(legacy_verdict, corrected)
            corrected = _STRENGTH_PATTERN.sub(legacy_strength, corrected)
            corrected = corrected.replace(
                legacy_strength,
                f"{legacy_strength}\n\n> **证据策略校正**：待核验原网页不能证明自身，且本轮未引用独立外部来源。",
                1,
            )
            changed = True

        update: dict = {}
        if corrected != original_content:
            update["messages"] = [last_message.model_copy(update={"content": corrected})]
        if workflow_report is not None:
            update["rumor_report"] = workflow_report
        elif decision is not None:
            update["rumor_report"] = {
                "schema_version": "rumorbuster-report-v1",
                "checkability": tool_payloads.get("classify_checkability"),
                "rag": tool_payloads.get("retrieve_verified_rumors"),
                "classifier_signal": tool_payloads.get("rumor_check"),
                "evidence": assess_args.get("evidence", []),
                "decision": decision,
                "original_url": assess_args.get("original_url"),
            }
        return update or None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)
