"""Rumor-agent-specific tools — wraps the fine-tuned classifier as a LangChain tool."""

import logging
import os

import requests
from langchain.tools import tool

logger = logging.getLogger(__name__)

_MODEL_INSTRUCTION = (
    "You are a professional rumor detection assistant. "
    "Determine whether the following text is a rumor. "
    "You must strictly output only one of the following options: "
    "'Yes', 'No', or 'Unknown'. "
    "If there is not enough information to verify the claim, output 'Unknown'."
)

_VERDICT_MAP = {"yes": "谣言", "no": "非谣言", "unknown": "存疑"}
_CONFIDENCE_MAP = {"yes": "85", "no": "90", "unknown": "50"}


def _parse_verdict(raw: str) -> tuple[str, str]:
    token = raw.strip().strip("'\"").lower()
    for key in _VERDICT_MAP:
        if key in token:
            return _VERDICT_MAP[key], _CONFIDENCE_MAP[key]
    return "存疑", "50"


@tool("rumor_check")
def rumor_check_tool(claim: str) -> str:
    """Call the fine-tuned rumor detection model to get a verdict on a claim.

    This tool sends the claim to a fine-tuned classifier that has been trained
    specifically on rumor detection datasets. It returns a structured verdict
    (谣言 / 非谣言 / 存疑) along with a confidence score.

    Use this tool AFTER gathering evidence from sub-agents, as the final
    classification step.

    Args:
        claim: The statement or claim to be checked for rumor classification.
    """
    base_url = os.getenv("RUMOR_MODEL_BASE_URL", "http://localhost:8000/v1")
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": "trained_model",
                "messages": [
                    {"role": "system", "content": _MODEL_INSTRUCTION},
                    {"role": "user", "content": claim},
                ],
                "max_tokens": 16,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw_label = resp.json()["choices"][0]["message"]["content"].strip()
        verdict_cn, confidence = _parse_verdict(raw_label)
        logger.info("rumor_check: verdict=%s (raw=%r)", verdict_cn, raw_label)
        return (
            f"微调模型判定结果：\n"
            f"- 原始输出: {raw_label}\n"
            f"- 判定: {verdict_cn}\n"
            f"- 置信度: {confidence}%"
        )
    except requests.exceptions.ConnectionError:
        logger.warning("rumor_check: fine-tuned model service unreachable at %s", base_url)
        return (
            f"微调模型服务不可达（{base_url}）。\n"
            "请确认 RUMOR_MODEL_BASE_URL 配置正确且模型服务已启动。\n"
            "本次将跳过微调模型判定，请根据已收集的证据直接进行综合分析。"
        )
    except Exception as exc:
        logger.error("rumor_check: failed: %s", exc)
        return f"微调模型调用失败: {exc}\n请根据已收集的证据直接进行综合分析。"
