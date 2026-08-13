"""Rumor-agent tools.

The fine-tuned model is intentionally exposed as a non-authoritative auxiliary
signal.  Evidence collection and the deterministic evidence policy remain the
only sources allowed to determine the final verdict.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from langchain.tools import tool

logger = logging.getLogger(__name__)

_MODEL_INSTRUCTION = (
    "You are a professional rumor detection assistant. Determine whether the "
    "following text is a rumor. You must strictly output only one of the "
    "following options: 'Yes', 'No', or 'Unknown'. If there is not enough "
    "information to verify the claim, output 'Unknown'."
)

_VALID_LABELS = {"rumor", "non_rumor", "uncertain"}
_LEGACY_LABELS = {
    "yes": "rumor",
    "no": "non_rumor",
    "unknown": "uncertain",
}


@dataclass(frozen=True)
class ModelSignal:
    """Normalized, explicitly non-authoritative classifier output."""

    label: str
    rationale: str = ""
    raw_label: str | None = None
    status: str = "ok"


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_model_signal(raw: str) -> ModelSignal:
    """Parse exact JSON or an exact legacy token without substring matching."""
    value = _strip_json_fence(raw)
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict):
        raw_label = payload.get("label")
        label = raw_label.strip().lower() if isinstance(raw_label, str) else ""
        if label in _VALID_LABELS:
            raw_rationale = payload.get("rationale")
            rationale = raw_rationale.strip() if isinstance(raw_rationale, str) else ""
            return ModelSignal(label, rationale, str(raw_label), "ok")
        if label in _LEGACY_LABELS:
            canonical = label.capitalize() if label != "unknown" else "Unknown"
            return ModelSignal(_LEGACY_LABELS[label], "", canonical, "ok")
        return ModelSignal(
            "uncertain",
            "模型未返回可识别的结构化标签",
            None,
            "invalid_output",
        )

    token_source = payload if isinstance(payload, str) else value
    token_match = re.fullmatch(
        r"[\s'\"“”‘’]*(yes|no|unknown)[\s'\"“”‘’.,!?。！？；;，,:：]*",
        str(token_source),
        flags=re.IGNORECASE,
    )
    if token_match:
        token = token_match.group(1).lower()
        canonical = token.capitalize() if token != "unknown" else "Unknown"
        return ModelSignal(_LEGACY_LABELS[token], "", canonical, "ok")
    return ModelSignal(
        "uncertain",
        "模型未返回可识别的结构化标签",
        None,
        "invalid_output",
    )


def _timeout_seconds(override: float | None = None) -> float:
    if override is not None:
        return max(0.1, float(override))
    try:
        configured = float(os.getenv("RUMOR_MODEL_TIMEOUT_SECONDS", "20"))
    except ValueError:
        configured = 20.0
    return min(120.0, max(1.0, configured))


def _model_api_style() -> str:
    return os.getenv("RUMOR_MODEL_API_STYLE", "openai_chat").strip().lower() or "openai_chat"


def _model_id() -> str:
    return (
        os.getenv(
            "RUMOR_MODEL_NAME",
            "congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets",
        ).strip()
        or "congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets"
    )


def _endpoint(base_url: str, api_style: str) -> str:
    base = base_url.rstrip("/")
    if api_style == "modelscope_chat":
        return f"{base}/chat" if base.endswith("/v1") else f"{base}/v1/chat"
    if api_style == "openai_chat":
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    raise ValueError(f"unsupported model API style: {api_style}")


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int(item) for key, item in value.items() if isinstance(item, int) and not isinstance(item, bool) and item >= 0}


def _audit_base(claim: str, *, started: float, request_id: str, called_at: str) -> dict[str, Any]:
    return {
        "latency_ms": max(0, round((time.monotonic() - started) * 1000)),
        "input_hash": hashlib.sha256(claim.encode("utf-8")).hexdigest(),
        "request_id": request_id,
        "called_at": called_at,
        "usage": {},
    }


def classify_claim_text(claim: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Call the configured fine-tuned model for one text-only claim.

    The returned audit deliberately excludes the endpoint, headers, API key and
    full environment. Only exact labels are accepted.
    """

    started = time.monotonic()
    called_at = datetime.now(UTC).isoformat()
    request_id = uuid.uuid4().hex
    base_url = os.getenv("RUMOR_MODEL_BASE_URL", "").strip()
    api_style = _model_api_style()
    audit = _audit_base(claim, started=started, request_id=request_id, called_at=called_at)
    if not base_url:
        return {
            "status": "unavailable",
            "raw_label": None,
            "mapped_label": "uncertain",
            **audit,
            "error_code": "classifier_not_configured",
        }
    try:
        endpoint = _endpoint(base_url, api_style)
    except ValueError:
        return {
            "status": "unavailable",
            "raw_label": None,
            "mapped_label": "uncertain",
            **audit,
            "error_code": "unsupported_api_style",
        }

    api_key = os.getenv("RUMOR_MODEL_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if api_style == "modelscope_chat":
        body = {
            "messages": [
                {"role": "system", "content": _MODEL_INSTRUCTION},
                {"role": "user", "content": claim},
            ],
            "max_new_tokens": 8,
            "temperature": 0,
            "top_p": 1,
            "top_k": 20,
            "repetition_penalty": 1,
        }
    else:
        body = {
            "model": _model_id(),
            "messages": [
                {"role": "system", "content": _MODEL_INSTRUCTION},
                {"role": "user", "content": claim},
            ],
            "max_tokens": 8,
            "temperature": 0,
        }

    budget = _timeout_seconds(timeout_seconds)
    deadline = started + budget
    response = None
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            response = requests.post(
                endpoint,
                json=body,
                headers=headers,
                timeout=remaining,
            )
            if getattr(response, "status_code", 200) == 502:
                if attempt == 0:
                    continue
                response = None
                break
            response.raise_for_status()
            break
        except requests.exceptions.ConnectionError:
            if attempt == 0:
                continue
            response = None
            break
        except Exception:
            response = None
            break

    audit = _audit_base(claim, started=started, request_id=request_id, called_at=called_at)
    if response is None:
        return {
            "status": "unavailable",
            "raw_label": None,
            "mapped_label": "uncertain",
            **audit,
            "error_code": "request_failed",
        }

    try:
        payload = response.json()
        if api_style == "modelscope_chat":
            raw = payload["response"]
        else:
            raw = payload["choices"][0]["message"]["content"]
        usage = _safe_usage(payload.get("usage"))
        signal = _parse_model_signal(str(raw))
    except Exception:
        return {
            "status": "invalid_output",
            "raw_label": None,
            "mapped_label": "uncertain",
            **audit,
            "error_code": "invalid_response_schema",
        }
    return {
        "status": signal.status,
        "raw_label": signal.raw_label,
        "mapped_label": signal.label,
        **audit,
        "usage": usage,
        **({"error_code": "invalid_label"} if signal.status != "ok" else {}),
    }


def aggregate_classifier_signal(
    results: list[dict[str, Any]],
    *,
    model_id: str | None = None,
    api_style: str | None = None,
) -> dict[str, Any]:
    successful = [item for item in results if item.get("status") == "ok"]
    if results and len(successful) == len(results):
        status = "ok"
    elif successful:
        status = "partial"
    else:
        status = "unavailable"
    labels = {str(item.get("mapped_label")) for item in successful}
    aggregate_label = next(iter(labels)) if len(labels) == 1 and "uncertain" not in labels and len(successful) == len(results) else "uncertain"
    rationale = "模型仅基于文本模式给出风险标签，没有读取本轮网页证据。" if successful else "微调模型服务暂时不可用，本轮不得据此判断真假。"
    return {
        "status": status,
        "role": "auxiliary_signal",
        "label": aggregate_label,
        "aggregate_label": aggregate_label,
        "rationale": rationale,
        "authoritative": False,
        "model_id": model_id or _model_id(),
        "api_style": api_style or _model_api_style(),
        "subclaims": results,
    }


@tool("rumor_check")
def rumor_check_tool(claim: str) -> str:
    """Classify the original claim as an auxiliary text-risk signal.

    The result never has authority over retrieved evidence or the deterministic
    evidence decision. It returns JSON with ``status``, ``role``, ``label``,
    ``rationale`` and ``authoritative``.

    Args:
        claim: The original normalized claim, without retrieved evidence.
    """
    result = classify_claim_text(claim)
    result.update({"claim_id": "claim-1", "text": claim})
    payload = aggregate_classifier_signal([result])
    logger.info(
        "rumor_check: status=%s label=%s request_id=%s",
        result.get("status"),
        result.get("mapped_label"),
        result.get("request_id"),
    )
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "ModelSignal",
    "_parse_model_signal",
    "aggregate_classifier_signal",
    "classify_claim_text",
    "rumor_check_tool",
]
