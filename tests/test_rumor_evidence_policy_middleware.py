"""Tests for deterministic URL-report evidence enforcement."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.rumor_evidence_policy_middleware import (
    RumorEvidencePolicyMiddleware,
)


def _fetch_message(url: str = "https://example.com") -> ToolMessage:
    return ToolMessage(
        name="web_fetch",
        tool_call_id="fetch-1",
        content=json.dumps(
            {
                "source_url": url,
                "requested_url": url,
                "title": "Example Domain",
                "content": "Example page body",
            }
        ),
    )


def _report(*, sources: str, verdict: str = "非谣言", strength: str = "高") -> str:
    return f"""## 谣言检测报告

### 原网页内容
网页内容摘要。

**判定结论**：{verdict}
**证据强度**：{strength}

### 来源
{sources}
"""


def _apply(messages):
    middleware = RumorEvidencePolicyMiddleware()
    return middleware.after_model({"messages": messages}, None)  # type: ignore[arg-type]


def test_url_report_is_downgraded_without_cited_independent_evidence():
    final = AIMessage(
        content=_report(sources="- [Example Domain](https://example.com) — 待核验原网页")
    )

    result = _apply(
        [
            HumanMessage(content="核验 https://example.com"),
            _fetch_message(),
            ToolMessage(
                name="task",
                tool_call_id="task-1",
                content='Task Succeeded. Result: {"results": []}',
            ),
            final,
        ]
    )

    assert result is not None
    corrected = result["messages"][0].content
    assert "**判定结论**：存疑（证据不足，未获得独立外部来源）" in corrected
    assert "**证据强度**：低" in corrected
    assert "证据策略校正" in corrected


def test_url_report_keeps_verdict_when_it_cites_independent_tool_evidence():
    final = AIMessage(
        content=_report(
            sources=(
                "- [Example Domain](https://example.com) — 待核验原网页\n"
                "- [IANA](https://www.iana.org/help/example-domains) — 独立说明"
            )
        )
    )

    result = _apply(
        [
            _fetch_message(),
            ToolMessage(
                name="task",
                tool_call_id="task-1",
                content=(
                    'Task Succeeded. Result: {"results": '
                    '[{"url": "https://www.iana.org/help/example-domains"}]}'
                ),
            ),
            final,
        ]
    )

    assert result is None


def test_url_report_removes_hallucinated_citation_then_downgrades():
    final = AIMessage(
        content=_report(
            sources=(
                "- [Example Domain](https://example.com)\n"
                "- [虚构来源](https://not-returned.invalid/report)"
            )
        )
    )

    result = _apply([_fetch_message(), final])

    assert result is not None
    corrected = result["messages"][0].content
    assert "https://not-returned.invalid/report" not in corrected
    assert "虚构来源（未验证链接已移除）" in corrected
    assert "**证据强度**：低" in corrected


def test_url_report_appends_missing_original_page_to_sources():
    final = AIMessage(
        content="""## 谣言检测报告

### 原网页内容
网页内容摘要。

**判定结论**：存疑
**证据强度**：低

### 来源
"""
    )

    result = _apply([_fetch_message(), final])

    assert result is not None
    corrected = result["messages"][0].content
    assert "[Example Domain](https://example.com)" in corrected


def test_tool_call_messages_are_not_modified():
    final = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "fetch-1",
                "name": "web_fetch",
                "args": {"url": "https://example.com"},
            }
        ],
    )

    assert _apply([final]) is None


def test_rule_decision_binds_markdown_and_projects_structured_state():
    evidence = {
        "id": "a-1",
        "title": "主管部门公告",
        "url": "https://authority.example/notice",
        "publisher": "主管部门",
        "stance": "refute",
        "source_level": "A",
        "directness": "direct",
        "authority_scope": True,
        "independent_group": "authority",
        "temporal_relevance": "current",
        "summary": "公告直接反驳待核验主张",
        "provenance": "web",
    }
    decision = {
        "verdict": "谣言",
        "strength": "high",
        "accepted_evidence_ids": ["a-1"],
        "excluded_evidence": [],
        "reason_codes": ["threshold_a"],
        "classifier_consistency": "conflict",
        "explanation": "A类主管来源达到门槛。",
    }
    assess_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "assess-1",
                "name": "assess_evidence",
                "args": {"evidence": [evidence]},
            }
        ],
    )
    final = AIMessage(
        content=_report(
            sources="- [主管部门公告](https://authority.example/notice)",
            verdict="非谣言",
            strength="低",
        )
    )

    result = _apply(
        [
            ToolMessage(
                name="classify_checkability",
                tool_call_id="route-1",
                content=json.dumps({"checkability": "checkable_now"}),
            ),
            ToolMessage(
                name="task",
                tool_call_id="task-1",
                content=json.dumps({"url": evidence["url"]}),
            ),
            assess_call,
            ToolMessage(
                name="assess_evidence",
                tool_call_id="assess-1",
                content=json.dumps(decision, ensure_ascii=False),
            ),
            final,
        ]
    )

    assert result is not None
    assert "**判定结论**：谣言" in result["messages"][0].content
    assert "**证据强度**：high" in result["messages"][0].content
    assert result["rumor_report"]["decision"] == decision
    assert result["rumor_report"]["evidence"] == [evidence]
