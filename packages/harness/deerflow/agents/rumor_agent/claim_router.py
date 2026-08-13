"""Conservative, deterministic pre-routing for clearly non-checkable claims."""

from __future__ import annotations

import re

from langchain.tools import tool

from deerflow.agents.rumor_agent.schemas import (
    Checkability,
    ClaimAssessment,
    ClaimContext,
    ClaimTemporality,
    ClaimType,
    Subclaim,
)

_SATIRE = re.compile(r"(?:开玩笑|纯属娱乐|段子|反讽|讽刺|恶搞)")
_OPINION = re.compile(r"(?:我觉得|我认为|在我看来|最好看|最难看|演技很差|太难吃|很无聊)")
_PRIVATE = re.compile(r"(?:内裤|私人聊天|私下说了什么|未公开的|家庭住址|银行卡密码|手机密码)")
_RANDOM_FUTURE = re.compile(r"(?:彩票|中奖号码|下一期号码|明天.*(?:毁灭|地震)|未来.*一定)")
_FUTURE_PREDICTION = re.compile(r"(?:预测|预言|将会发生|一定会发生|明天会不会|下周会不会)")


def assess_checkability(claim: str) -> ClaimAssessment:
    """Route only clear boundary cases; ambiguous statements remain public facts."""
    normalized = " ".join(claim.split()).strip()
    if len(normalized) < 4:
        return ClaimAssessment(
            claim=normalized,
            claim_type=ClaimType.UNCLEAR,
            checkability=Checkability.NEEDS_CLARIFICATION,
            reason="缺少足够具体、可验证的主张。",
        )
    if _SATIRE.search(normalized):
        return ClaimAssessment(
            claim=normalized,
            claim_type=ClaimType.SATIRE,
            checkability=Checkability.NOT_A_FACTUAL_CLAIM,
            reason="文本明确标记为玩笑、反讽或娱乐表达。",
        )
    if _OPINION.search(normalized):
        return ClaimAssessment(
            claim=normalized,
            claim_type=ClaimType.OPINION,
            checkability=Checkability.NOT_A_FACTUAL_CLAIM,
            reason="主张主要表达个人评价，缺少统一客观真假标准。",
        )
    if _PRIVATE.search(normalized):
        return ClaimAssessment(
            claim=normalized,
            claim_type=ClaimType.PRIVATE_FACT,
            checkability=Checkability.NOT_PUBLICLY_CHECKABLE,
            reason="主张涉及不应通过公开检索推测的私人事实。",
        )
    if _RANDOM_FUTURE.search(normalized) or _FUTURE_PREDICTION.search(normalized):
        return ClaimAssessment(
            claim=normalized,
            claim_type=ClaimType.FUTURE_PREDICTION,
            checkability=Checkability.CHECKABLE_LATER,
            reason="主张描述尚未发生或具有随机性的未来结果。",
        )
    return ClaimAssessment(
        claim=normalized,
        claim_type=ClaimType.PUBLIC_FACT,
        checkability=Checkability.CHECKABLE_NOW,
        reason="主张包含原则上可以通过公开证据核验的事实内容。",
    )


@tool("classify_checkability")
def classify_checkability_tool(
    claim: str,
    subclaims: list[dict] | None = None,
    temporality: str = "unknown",
    event_date: str | None = None,
    source_url: str | None = None,
) -> str:
    """Classify whether a normalized claim can be publicly checked now.

    Args:
        claim: One explicit, normalized claim.
    """
    assessment = assess_checkability(claim)
    parsed_subclaims: list[Subclaim] = []
    for index, raw in enumerate((subclaims or [])[:3]):
        try:
            parsed_subclaims.append(Subclaim.model_validate(raw))
        except Exception:
            continue
    if not parsed_subclaims:
        parsed_subclaims = [Subclaim(id="claim-1", text=assessment.claim, material=True)]
    try:
        parsed_temporality = ClaimTemporality(temporality)
    except ValueError:
        parsed_temporality = ClaimTemporality.UNKNOWN
    context = ClaimContext(
        normalized_claim=assessment.claim,
        subclaims=parsed_subclaims,
        temporality=parsed_temporality,
        event_date=event_date,
        source_url=source_url,
    )
    return assessment.model_copy(update={"claim_context": context}).model_dump_json()


__all__ = ["assess_checkability", "classify_checkability_tool"]
