"""Regression tests for workflow gating, source policy, subclaims, and timeline v2."""

import json
from datetime import date, timedelta

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.rumor_evidence_policy_middleware import (
    RumorEvidencePolicyMiddleware,
)
from deerflow.agents.middlewares.rumor_workflow_middleware import (
    RumorWorkflowMiddleware,
    _normalize_task_message,
    derive_workflow,
    parse_research_result,
)
from deerflow.agents.rumor_agent.evidence import decide_evidence
from deerflow.agents.rumor_agent.schemas import ClaimContext, EvidenceItem
from deerflow.agents.rumor_agent.source_policy import grade_source, normalize_evidence_items
from deerflow.agents.rumor_agent.timeline import build_timeline


def _tool(name: str, payload: dict, call_id: str) -> ToolMessage:
    return ToolMessage(name=name, tool_call_id=call_id, content=json.dumps(payload, ensure_ascii=False))


def _item(
    evidence_id: str,
    *,
    url: str,
    stance: str = "support",
    level: str = "B",
    published_at: str = "2026-08-01",
    claim_ids: list[str] | None = None,
    summary: str | None = None,
) -> dict:
    return {
        "id": evidence_id,
        "title": f"来源{evidence_id}",
        "url": url,
        "publisher": evidence_id,
        "published_at": published_at,
        "stance": stance,
        "source_level": level,
        "directness": "direct",
        "authority_scope": level == "A",
        "independent_group": evidence_id,
        "temporal_relevance": "current",
        "current_validity_confirmed": True,
        "fetched_at": "2026-08-12T00:00:00+08:00",
        "excerpt": summary or f"{evidence_id}的独立正文证据",
        "document_hash": "b" * 64,
        "fetch_status": "fetched",
        "extraction_status": "ok",
        "claim_ids": claim_ids or [],
        "summary": summary or f"{evidence_id}的独立正文证据",
        "provenance": "web",
    }


def test_workflow_derives_required_stages_from_latest_turn_only():
    first = HumanMessage(content="请核验某地发布了停课通知")
    workflow = derive_workflow(
        {"messages": [first]},
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=False,
    )
    assert workflow["stage"] == "checkability"

    checkability = {
        "claim": "某地发布了停课通知",
        "claim_type": "public_fact",
        "checkability": "checkable_now",
        "reason": "可公开核验",
        "claim_context": {
            "normalized_claim": "某地发布了停课通知",
            "subclaims": [{"id": "claim-1", "text": "某地发布了停课通知", "material": True}],
            "temporality": "current_status",
        },
    }
    workflow = derive_workflow(
        {"messages": [first, _tool("classify_checkability", checkability, "c1")]},
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=False,
    )
    assert workflow["stage"] == "rag"

    second = HumanMessage(content="你好")
    workflow = derive_workflow(
        {"messages": [first, _tool("classify_checkability", checkability, "c1"), second]},
        web_search_enabled=True,
        web_fetch_enabled=True,
        classifier_enabled=True,
    )
    assert workflow["stage"] == "conversation"
    assert workflow["trace"] == []


def test_gate_replaces_missing_duplicate_or_unauthorized_tool_calls():
    gate = RumorWorkflowMiddleware(
        web_search_enabled=True,
        web_fetch_enabled=True,
        classifier_enabled=False,
    )
    human = HumanMessage(content="请核验某地发布了停课通知")
    for calls in (
        [],
        [{"id": "wrong", "name": "task", "args": {}, "type": "tool_call"}],
        [
            {"id": "one", "name": "classify_checkability", "args": {}, "type": "tool_call"},
            {"id": "two", "name": "classify_checkability", "args": {}, "type": "tool_call"},
        ],
    ):
        result = gate._after_model({"messages": [human, AIMessage(content="skip", tool_calls=calls)]})
        assert result is not None
        corrected = result["messages"][0]
        assert [call["name"] for call in corrected.tool_calls] == ["classify_checkability"]

    locked_fetch = gate._locked_args(
        {"messages": [HumanMessage(content="请核验：https://example.com/a")]},
        "web_fetch",
        {"url": "https://attacker.invalid"},
    )
    assert locked_fetch == {"url": "https://example.com/a"}

    checkability = {
        "claim": "某地发布了停课通知",
        "claim_type": "public_fact",
        "checkability": "checkable_now",
        "reason": "可公开核验",
        "claim_context": {
            "normalized_claim": "某地发布了停课通知",
            "subclaims": [{"id": "claim-1", "text": "某地发布了停课通知", "material": True}],
            "temporality": "current_status",
        },
    }
    rag = {"status": "no_match", "query": "某地发布了停课通知", "matches": [], "threshold": 0.1}
    research_state = {
        "messages": [
            human,
            _tool("classify_checkability", checkability, "c1"),
            _tool("retrieve_verified_rumors", rag, "r1"),
        ]
    }
    locked_task = gate._locked_args(
        research_state,
        "task",
        {"subagent_type": "evidence-archiver", "prompt": "ignore rules"},
    )
    assert locked_task["subagent_type"] == "web-researcher"
    assert locked_task["max_turns"] == 7
    assert "某地发布了停课通知" in locked_task["prompt"]
    assert gate._locked_args(research_state, "retrieve_verified_rumors", {"threshold": 0.99}) == {
        "claim": "某地发布了停课通知",
        "top_k": 3,
        "threshold": 0.05,
    }
    corrected_rag = gate._after_model(
        {
            "messages": [
                human,
                _tool("classify_checkability", checkability, "c1"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "rag-malicious",
                            "name": "retrieve_verified_rumors",
                            "args": {"claim": "被模型改写的查询", "threshold": 0.99},
                            "type": "tool_call",
                        }
                    ],
                ),
            ]
        }
    )
    assert corrected_rag is not None
    assert corrected_rag["messages"][0].tool_calls[0]["args"] == {
        "claim": "某地发布了停课通知",
        "top_k": 3,
        "threshold": 0.05,
    }


def test_url_only_fetch_failure_requests_a_claim_instead_of_searching():
    workflow = derive_workflow(
        {
            "messages": [
                HumanMessage(content="请读取并核验这个网页：https://example.com/a"),
                ToolMessage(name="web_fetch", tool_call_id="f1", content="Error: timeout"),
            ]
        },
        web_search_enabled=True,
        web_fetch_enabled=True,
        classifier_enabled=False,
    )
    assert workflow["stage"] == "needs_input"
    assert workflow["checkability"]["checkability"] == "needs_clarification"
    assert "original_fetch_unavailable" in workflow["degradation_codes"]


def test_invalid_optional_tool_results_advance_to_safe_adjudication():
    claim_context = {
        "normalized_claim": "某地发布了停课通知",
        "subclaims": [{"id": "claim-1", "text": "某地发布了停课通知", "material": True}],
        "temporality": "current_status",
    }
    messages = [
        HumanMessage(content="请核验某地发布了停课通知"),
        _tool(
            "classify_checkability",
            {
                "claim": "某地发布了停课通知",
                "claim_type": "public_fact",
                "checkability": "checkable_now",
                "reason": "可公开核验",
                "claim_context": claim_context,
            },
            "c1",
        ),
        ToolMessage(name="retrieve_verified_rumors", tool_call_id="r1", content="Error: timeout"),
        ToolMessage(name="rumor_check", tool_call_id="m1", content="not json"),
    ]
    workflow = derive_workflow(
        {"messages": messages},
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=True,
    )
    assert workflow["stage"] == "adjudicate"
    assert workflow["rag_result"]["status"] == "unavailable"
    assert workflow["classifier_signal"]["status"] == "unavailable"
    assert {"rag_unavailable", "classifier_unavailable"} <= set(workflow["degradation_codes"])
    assert {item["tool"] for item in workflow["trace"] if item["status"] == "degraded"} == {
        "retrieve_verified_rumors",
        "rumor_check",
    }

    messages.append(ToolMessage(name="assess_evidence", tool_call_id="a1", content="Error: tool failed"))
    workflow = derive_workflow(
        {"messages": messages},
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=True,
    )
    assert workflow["stage"] == "report"
    assert workflow["decision"]["verdict"] == "证据不足"
    assert "adjudicator_tool_unavailable" in workflow["degradation_codes"]


def test_research_json_is_parsed_directly_and_invalid_items_are_recorded():
    result, rejected = parse_research_result('Task Succeeded. Result: {"status":"ok","evidence":[' + json.dumps(_item("ok", url="https://reuters.com/a"), ensure_ascii=False) + ',{"id":"bad"}],"notes":"done"}')
    assert result.status == "ok"
    assert [item.id for item in result.evidence] == ["ok"]
    assert rejected[0]["reason_code"] == "invalid_schema"

    normalized_message = _normalize_task_message(
        ToolMessage(
            name="task",
            tool_call_id="task-normalize",
            content="研究员解释文字\n```json\n"
            + json.dumps(
                {"status": "ok", "evidence": [_item("normalized", url="https://media.example/a")]},
                ensure_ascii=False,
            )
            + "\n```",
        )
    )
    normalized_payload = json.loads(normalized_message.content)
    assert normalized_payload["status"] == "ok"
    assert normalized_payload["evidence"][0]["id"] == "normalized"


def test_research_json_accepts_fenced_and_prose_prefixed_payloads():
    payload = json.dumps({"status": "ok", "evidence": [_item("fenced", url="https://media.example/fenced")]}, ensure_ascii=False)

    fenced_result, _ = parse_research_result("```json\n" + payload + "\n```")
    assert fenced_result.status == "ok"
    assert [item.id for item in fenced_result.evidence] == ["fenced"]

    prose_result, _ = parse_research_result("以下是我检索到的证据，请据此判断：\n" + payload + "\n希望有帮助。")
    assert prose_result.status == "ok"
    assert [item.id for item in prose_result.evidence] == ["fenced"]


def test_research_json_skips_stray_fragments_and_requires_expected_keys():
    result, _ = parse_research_result('{"a":1}\n\n{"status":"ok","evidence":[' + json.dumps(_item("keyed", url="https://media.example/keyed"), ensure_ascii=False) + '],"notes":"done"}')
    assert result.status == "ok"
    assert [item.id for item in result.evidence] == ["keyed"]

    stray_only, rejected = parse_research_result('{"a":1}\n\n{"b":2}')
    assert stray_only.status == "unavailable"
    assert rejected[0]["reason_code"] == "invalid_research_json"

    array_output, rejected = parse_research_result('[{"id":"x"}]')
    assert array_output.status == "unavailable"
    assert rejected[0]["reason_code"] == "invalid_research_json"


def test_invalid_timeline_event_type_is_dropped_not_rejected():
    payload = json.dumps(
        {
            "status": "ok",
            "evidence": [_item("context-type", url="https://media.example/context") | {"timeline_event_type": "context"}],
            "notes": "done",
        },
        ensure_ascii=False,
    )
    result, rejected = parse_research_result(payload)

    assert result.status == "ok"
    assert result.evidence[0].timeline_event_type is None
    assert not any(item["reason_code"] == "invalid_schema" for item in rejected)


def test_invalid_temporal_relevance_is_normalized_not_rejected():
    payload = json.dumps(
        {
            "status": "ok",
            "evidence": [_item("recent-type", url="https://media.example/recent") | {"temporal_relevance": "recent"}],
            "notes": "done",
        },
        ensure_ascii=False,
    )
    result, rejected = parse_research_result(payload)

    assert result.status == "ok"
    assert result.evidence[0].temporal_relevance.value == "unknown"
    assert not any(item["reason_code"] == "invalid_schema" for item in rejected)


def test_scripted_full_workflow_reaches_binding_decision_and_timeline():
    claim = "某地发布了停课通知"
    context = {
        "normalized_claim": claim,
        "subclaims": [{"id": "claim-1", "text": claim, "material": True}],
        "temporality": "event_bound",
        "event_date": "2026-08-01",
    }
    messages = [HumanMessage(content=f"请核验：{claim}")]
    capabilities = dict(web_search_enabled=True, web_fetch_enabled=False, classifier_enabled=False)
    assert derive_workflow({"messages": messages}, **capabilities)["stage"] == "checkability"

    messages.append(
        _tool(
            "classify_checkability",
            {
                "claim": claim,
                "claim_type": "public_fact",
                "checkability": "checkable_now",
                "reason": "可公开核验",
                "claim_context": context,
            },
            "c1",
        )
    )
    assert derive_workflow({"messages": messages}, **capabilities)["stage"] == "rag"

    messages.append(
        _tool(
            "retrieve_verified_rumors",
            {"status": "no_match", "query": claim, "matches": [], "threshold": 0.1},
            "r1",
        )
    )
    assert derive_workflow({"messages": messages}, **capabilities)["stage"] == "research"

    evidence = [
        _item("b1", url="https://media-one.example/a", level="B", published_at="2026-08-01", claim_ids=["claim-1"]),
        _item("b2", url="https://media-two.example/b", level="B", published_at="2026-08-02", claim_ids=["claim-1"]),
        _item("spread", url="https://social.example/c", level="C", published_at="2026-08-03", claim_ids=["claim-1"]),
    ]
    messages.append(
        ToolMessage(
            name="task",
            tool_call_id="t1",
            content="Task Succeeded. Result: " + json.dumps({"status": "ok", "evidence": evidence}, ensure_ascii=False),
        )
    )
    workflow = derive_workflow({"messages": messages}, **capabilities)
    assert workflow["stage"] == "adjudicate"
    decision = decide_evidence(
        evidence=workflow["evidence"],
        allowed_urls={item["url"] for item in evidence},
        claim_context=context,
    )
    assert decision.verdict == "非谣言"

    messages.append(_tool("assess_evidence", decision.model_dump(mode="json"), "a1"))
    workflow = derive_workflow({"messages": messages}, **capabilities)
    assert workflow["stage"] == "report"
    assert workflow["decision"]["verdict"] == "非谣言"
    assert workflow["timeline"]["timeline_status"] == "ready"
    assert all(event["evidence_id"] in {item["id"] for item in evidence} for event in workflow["timeline"]["events"])


def test_source_policy_downgrades_unknown_and_stale_current_sources():
    old_date = (date.today() - timedelta(days=500)).isoformat()
    raw = EvidenceItem.model_validate(_item("unknown", url="https://ordinary.invalid/post", level="A", published_at=old_date))
    raw = raw.model_copy(update={"current_validity_confirmed": False})
    normalized, errors = normalize_evidence_items(
        [raw],
        ClaimContext.model_validate(
            {
                "normalized_claim": "目前该政策仍然有效",
                "temporality": "current_status",
                "subclaims": [{"id": "claim-1", "text": "目前该政策仍然有效"}],
            }
        ),
    )
    assert normalized[0].source_level.value == "D"
    assert normalized[0].temporal_relevance.value == "stale"
    assert errors == {"unknown": "stale_current_status"}


def test_official_authority_scope_is_verified_from_registry_not_model_boolean():
    health = EvidenceItem.model_validate(_item("health", url="https://www.who.int/health-topic", level="A") | {"authority_scope": False, "authority_reason": "模型未判断"})
    unrelated = EvidenceItem.model_validate(_item("parking", url="https://www.who.int/parking", level="A") | {"authority_scope": True, "authority_reason": "模型声称匹配"})
    normalized, _ = normalize_evidence_items(
        [health, unrelated],
        ClaimContext.model_validate(
            {
                "normalized_claim": "WHO发布了新的疫苗健康建议",
                "temporality": "current_status",
                "subclaims": [{"id": "claim-1", "text": "WHO发布了新的疫苗健康建议"}],
            }
        ),
    )
    assert normalized[0].source_level.value == "A"
    assert normalized[0].authority_scope is True

    unrelated_normalized, _ = normalize_evidence_items(
        [unrelated],
        ClaimContext.model_validate(
            {
                "normalized_claim": "某城市今天调整了停车收费",
                "temporality": "current_status",
                "subclaims": [{"id": "claim-1", "text": "某城市今天调整了停车收费"}],
            }
        ),
    )
    assert unrelated_normalized[0].source_level.value == "B"
    assert unrelated_normalized[0].authority_scope is False


def test_cdc_tuskegee_archive_is_scope_matched_a_evidence():
    item = EvidenceItem.model_validate(
        _item(
            "tuskegee-cdc",
            url="https://www.cdc.gov/tuskegee/about/index.html",
            level="C",
            published_at=None,
            claim_ids=["claim-1"],
        )
    )
    context = ClaimContext.model_validate(
        {
            "normalized_claim": "美国公共卫生机构曾开展塔斯基吉梅毒研究",
            "temporality": "event_bound",
            "temporality_basis": "historical_marker",
            "subclaims": [
                {
                    "id": "claim-1",
                    "text": "美国公共卫生机构曾开展塔斯基吉梅毒研究",
                }
            ],
            "domain": "medical",
        }
    )

    grade = grade_source(item, context)
    normalized, errors = normalize_evidence_items([item], context)

    assert grade.verified.value == "A"
    assert grade.authority_scope is True
    assert normalized[0].temporal_relevance.value == "event_match"
    assert errors == {}


def test_old_current_evidence_needs_a_newer_direct_confirmation():
    old_date = (date.today() - timedelta(days=500)).isoformat()
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    old = EvidenceItem.model_validate(
        _item(
            "old",
            url="https://www.who.int/old-guidance",
            level="A",
            published_at=old_date,
            claim_ids=["claim-1"],
        )
        | {"current_validity_confirmed": True}
    )
    context = ClaimContext.model_validate(
        {
            "normalized_claim": "目前该疫苗健康指南仍然有效",
            "temporality": "current_status",
            "subclaims": [{"id": "claim-1", "text": "目前该疫苗健康指南仍然有效"}],
        }
    )
    stale, stale_errors = normalize_evidence_items([old], context)
    assert stale[0].temporal_relevance.value == "stale"
    assert stale[0].current_validity_confirmed is False
    assert stale_errors == {"old": "stale_current_status"}

    newer = EvidenceItem.model_validate(
        _item(
            "newer",
            url="https://www.reuters.com/health/current-guidance",
            level="B",
            published_at=recent_date,
            claim_ids=["claim-1"],
        )
    )
    confirmed, errors = normalize_evidence_items([old, newer], context)
    assert confirmed[0].temporal_relevance.value == "current"
    assert confirmed[0].current_validity_confirmed is True
    assert errors == {}


def test_historical_evidence_is_not_expired_and_may_omit_page_date():
    old = EvidenceItem.model_validate(
        _item(
            "cia-record",
            url="https://www.cia.gov/readingroom/document/example",
            level="A",
            published_at="1977-09-21",
            claim_ids=["claim-1"],
        )
    )
    undated = EvidenceItem.model_validate(
        _item(
            "cdc-archive",
            url="https://www.cdc.gov/tuskegee/about/index.html",
            level="A",
            published_at=None,
            claim_ids=["claim-1"],
        )
    )
    context = ClaimContext.model_validate(
        {
            "normalized_claim": "美国政府曾开展塔斯基吉未治疗梅毒研究",
            "temporality": "event_bound",
            "temporality_basis": "historical_marker",
            "subclaims": [{"id": "claim-1", "text": "美国政府曾开展该研究"}],
        }
    )

    normalized, errors = normalize_evidence_items([old, undated], context)

    assert errors == {}
    assert {item.temporal_relevance.value for item in normalized} == {"event_match"}


def test_subclaims_produce_misleading_without_a_free_boolean():
    decision = decide_evidence(
        evidence=[
            _item("support", url="https://agency-one.example/a", stance="support", level="A", claim_ids=["c1"]),
            _item("refute", url="https://agency-two.example/b", stance="refute", level="A", claim_ids=["c2"]),
        ],
        claim_context={
            "normalized_claim": "事件发生且造成十人受伤",
            "subclaims": [
                {"id": "c1", "text": "事件发生", "material": True},
                {"id": "c2", "text": "造成十人受伤", "material": True},
            ],
            "temporality": "event_bound",
        },
    )
    assert decision.verdict == "误导"
    assert decision.subclaim_decisions == {"c1": "非谣言", "c2": "谣言"}


def test_timeline_requires_three_traceable_dated_events():
    evidence = [
        _item("one", url="https://one.example/a", published_at="2026-07-01"),
        _item("two", url="https://two.example/b", published_at="2026-07-02"),
        _item("three", url="https://three.example/c", stance="refute", published_at="2026-07-03"),
    ]
    ready = build_timeline(
        evidence=evidence,
        decision={
            "verdict": "非谣言",
            "strength": "medium",
            "accepted_evidence_ids": ["one", "two"],
            "explanation": "达到门槛",
        },
    )
    assert ready.timeline_status.value == "ready"
    assert len(ready.events) == 3
    assert ready.events[0].event_type.value == "earliest_found"
    assert ready.events[2].used_for_decision is False

    insufficient = build_timeline(
        evidence=evidence[:2],
        decision={"verdict": "非谣言", "strength": "medium", "explanation": "达到门槛"},
    )
    assert insufficient.timeline_status.value == "insufficient"
    assert insufficient.events == []

    without_fetch_trace = [dict(item) for item in evidence]
    for item in without_fetch_trace:
        item.pop("fetched_at")
    untraceable = build_timeline(
        evidence=without_fetch_trace,
        decision={"verdict": "非谣言", "strength": "medium", "explanation": "达到门槛"},
    )
    assert untraceable.timeline_status.value == "insufficient"


def test_timeline_does_not_fabricate_ready_state_when_dedicated_research_failed():
    evidence = [
        _item("one", url="https://one.example/a", published_at="2026-07-01"),
        _item("two", url="https://two.example/b", published_at="2026-07-02"),
        _item("three", url="https://three.example/c", published_at="2026-07-03"),
    ]
    result = build_timeline(
        evidence=evidence,
        decision={"verdict": "证据不足", "strength": "insufficient", "explanation": "门槛不足"},
        timeline_research_status="unavailable",
    )

    assert result.timeline_status.value == "insufficient"
    assert result.events == []
    assert "不使用普通取证或历史RAG拼接时间线" in result.note


def test_timeline_only_material_never_changes_rule_verdict():
    timeline_items = [
        _item(
            f"timeline-{index}",
            url=f"https://timeline-{index}.example/article",
            stance="refute",
            level="A",
        )
        | {"timeline_only": True, "timeline_event_type": "spread"}
        for index in range(1, 4)
    ]

    decision = decide_evidence(evidence=timeline_items)
    timeline = build_timeline(evidence=timeline_items, decision=decision)

    assert decision.verdict == "证据不足"
    assert all(item.reason_code == "timeline_only" for item in decision.excluded_evidence)
    assert timeline.timeline_status.value == "ready"
    assert all(event.used_for_decision is False for event in timeline.events)


def test_final_policy_generates_v2_report_when_model_omits_template():
    workflow = {
        "stage": "report",
        "normalized_claim": "测试主张",
        "checkability": {"checkability": "checkable_now", "reason": "可核验"},
        "capabilities": {"rag": True},
        "evidence": [],
        "decision": {
            "verdict": "证据不足",
            "strength": "insufficient",
            "accepted_evidence_ids": [],
            "excluded_evidence": [],
            "reason_codes": ["threshold_not_met"],
            "classifier_consistency": "unavailable_or_uncertain",
            "explanation": "没有达到证据门槛。",
        },
        "timeline": {"timeline_status": "insufficient", "events": [], "note": "证据不足"},
        "trace": [],
        "degradation_codes": ["research_unavailable"],
    }
    result = RumorEvidencePolicyMiddleware().after_model(
        {"messages": [AIMessage(content="我觉得可能是真的")], "rumor_workflow": workflow},
        None,
    )
    assert result is not None
    assert result["rumor_report"]["schema_version"] == "rumorbuster-report-v2"
    assert "## 谣言检测报告" in result["messages"][0].content
    assert "**判定结论**：证据不足" in result["messages"][0].content
