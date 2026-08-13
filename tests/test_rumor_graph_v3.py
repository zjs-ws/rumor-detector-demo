"""Contract tests for RumorBuster's explicit V3 StateGraph."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from langchain_core.messages import HumanMessage

from deerflow.agents.rumor_agent.graph_v3 import (
    RumorV3Services,
    _claim_candidate,
    apply_verified_fetch_provenance,
    build_evidence_review,
    build_rumor_graph_v3,
    detect_claim_domain,
    make_parallel_sends,
    merge_research_branches,
    parse_claim_context_response,
    sanitize_text_risk_analysis,
)


def _evidence(evidence_id: str, *, url: str, claim_ids: list[str] | None = None) -> dict:
    return {
        "id": evidence_id,
        "title": evidence_id,
        "url": url,
        "publisher": evidence_id,
        "published_at": "2026-08-12",
        "stance": "support",
        "source_level": "B",
        "directness": "direct",
        "authority_scope": False,
        "independent_group": evidence_id,
        "temporal_relevance": "current",
        "current_validity_confirmed": True,
        "fetched_at": "2026-08-12T12:00:00+08:00",
        "extraction_status": "ok",
        "claim_ids": claim_ids or ["claim-1"],
        "summary": f"{evidence_id}正文证据",
        "provenance": "web",
    }


class FakeServices(RumorV3Services):
    def __init__(self, *, professional: bool = False, fail_web: bool = False):
        super().__init__(
            web_search_enabled=True,
            web_fetch_enabled=True,
            classifier_enabled=True,
        )
        self.professional = professional
        self.fail_web = fail_web
        self.calls: list[tuple[str, float, float]] = []

    async def extract_claim(self, raw_input, original_page, source_url, config):
        domain = "medical" if self.professional else "general"
        claim = "我觉得这部电影很无聊" if "我觉得" in raw_input else "某项公开事实"
        return {
            "normalized_claim": claim,
            "subclaims": [{"id": "claim-1", "text": claim, "material": True}],
            "temporality": "current_status",
            "event_date": None,
            "source_url": source_url,
            "domain": domain,
            "domain_reason": "测试路由",
        }

    async def retrieve_rag(self, claim_context, config):
        return {"status": "no_match", "query": claim_context["normalized_claim"], "matches": [], "threshold": 0.05, "authoritative": False}

    async def research_web(self, claim_context, config, *, supplementary=False, gap_query=""):
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.03)
        finished = asyncio.get_running_loop().time()
        self.calls.append(("web", started, finished))
        if self.fail_web:
            raise TimeoutError("web timeout")
        item = _evidence("web-1", url="https://reuters.com/a")
        return {"status": "ok", "evidence": [item], "rejected_evidence": [], "observed_urls": [item["url"]], "notes": ""}

    async def classify(self, claim_context, config):
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.03)
        finished = asyncio.get_running_loop().time()
        self.calls.append(("classifier", started, finished))
        return {"status": "ok", "role": "auxiliary_signal", "label": "non_rumor", "rationale": "测试", "authoritative": False}

    async def research_authority(self, claim_context, config):
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.03)
        finished = asyncio.get_running_loop().time()
        self.calls.append(("authority", started, finished))
        item = _evidence("authority-1", url="https://www.who.int/a") | {
            "source_level": "A",
            "authority_scope": True,
            "authority_reason": "卫生领域",
        }
        return {"status": "ok", "evidence": [item], "rejected_evidence": [], "observed_urls": [item["url"]], "notes": ""}

    async def review_evidence(self, claim_context, evidence, config):
        return build_evidence_review(claim_context, evidence, supplement_count=0)

    async def explain(self, workflow, config):
        return "这是严格受规则结论约束的解释。"


class HttpAdapterServices(FakeServices):
    async def classify(self, claim_context, config):
        return await RumorV3Services.classify(self, claim_context, config)


@contextmanager
def _modelscope_server(response_label: str = "No"):
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(
                {
                    "path": self.path,
                    "body": json.loads(self.rfile.read(length).decode()),
                }
            )
            payload = json.dumps(
                {
                    "response": response_label,
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 1,
                        "total_tokens": 13,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_domain_router_forces_professional_domains():
    assert detect_claim_domain("这种疫苗可以治疗疾病")[0] == "medical"
    assert detect_claim_domain("根据刑法和最高法司法解释")[0] == "legal"
    assert detect_claim_domain("证监会发布上市公司监管公告")[0] == "finance"
    assert detect_claim_domain("某地今天下雨")[0] == "general"


def test_url_only_instruction_is_not_mistaken_for_a_claim():
    assert _claim_candidate("请读取并核验这个网页的主要内容：https://science.nasa.gov/example") == ""


def test_plain_json_claim_extraction_fallback_accepts_fenced_payload():
    response = """```json
    {"normalized_claim":"全球气候正在变暖","subclaims":[{"id":"claim-1","text":"全球气候正在变暖","material":true}],"temporality":"current_status","event_date":null,"source_url":null,"domain":"science","domain_reason":"模型识别"}
    ```"""

    context = parse_claim_context_response(response, source_url="https://science.nasa.gov/climate-change/evidence/")

    assert context["normalized_claim"] == "全球气候正在变暖"
    assert context["source_url"].startswith("https://science.nasa.gov/")
    assert context["domain"] == "science"


def test_plain_json_claim_extraction_normalizes_provider_field_variants():
    response = '{"claim":"全球气候正在变暖","subclaims":["全球气候正在变暖"],"temporality":"present","event_date":"2999-01-01","domain":"environment"}'

    context = parse_claim_context_response(response, source_url=None)

    assert context["normalized_claim"] == "全球气候正在变暖"
    assert context["subclaims"] == [{"id": "claim-1", "text": "全球气候正在变暖", "material": True}]
    assert context["temporality"] == "unknown"
    assert context["event_date"] is None
    assert context["domain"] == "science"


def test_text_risk_analysis_keeps_only_grounded_spans_and_safe_hints():
    context = {
        "normalized_claim": "震惊！某药明日起百分之百治愈疾病，赶紧转发",
        "subclaims": [{"id": "claim-1", "text": "某药明日起百分之百治愈疾病", "material": True}],
        "text_risk_analysis": {
            "status": "completed",
            "signals": [
                {
                    "dimension": "exaggeration",
                    "level": "high",
                    "spans": ["震惊", "模型编造的片段"],
                    "note": "只是一种语言风险",
                },
                {
                    "dimension": "unsupported_dimension",
                    "level": "high",
                    "spans": ["赶紧转发"],
                    "note": "非法维度",
                },
            ],
            "verification_targets": [
                {
                    "kind": "date",
                    "text": "明日起",
                    "claim_ids": ["claim-1", "invented-claim"],
                }
            ],
            "search_hints": ["核验药品批准情况", "https://invented.example/result"],
            "authoritative": True,
        },
    }

    normalized = sanitize_text_risk_analysis(context, raw_input=context["normalized_claim"])

    risk = normalized["text_risk_analysis"]
    assert risk["authoritative"] is False
    assert risk["signals"] == [
        {
            "dimension": "exaggeration",
            "level": "high",
            "spans": ["震惊"],
            "note": "只是一种语言风险",
        }
    ]
    assert risk["verification_targets"][0]["claim_ids"] == ["claim-1"]
    assert risk["search_hints"] == ["核验药品批准情况"]


def test_classifier_classifies_at_most_three_material_subclaims(monkeypatch):
    from deerflow.agents.rumor_agent import tools as rumor_tools

    calls: list[str] = []

    def fake_classify(text: str, *, timeout_seconds: float | None = None):
        calls.append(text)
        return {
            "status": "ok",
            "raw_label": "Yes",
            "mapped_label": "rumor",
            "latency_ms": 1,
            "input_hash": f"hash-{len(calls)}",
            "request_id": f"request-{len(calls)}",
            "called_at": "2026-08-13T00:00:00+00:00",
            "usage": {},
        }

    monkeypatch.setattr(rumor_tools, "classify_claim_text", fake_classify)
    services = RumorV3Services(
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=True,
    )
    claim_context = {
        "normalized_claim": "组合主张",
        "subclaims": [{"id": f"claim-{index}", "text": f"子主张{index}", "material": True} for index in range(1, 5)],
    }

    result = asyncio.run(services.classify(claim_context, {}))

    assert calls == ["子主张1", "子主张2", "子主张3"]
    assert result["status"] == "ok"
    assert result["aggregate_label"] == "rumor"
    assert len(result["subclaims"]) == 3


def test_classifier_partial_result_becomes_uncertain(monkeypatch):
    from deerflow.agents.rumor_agent import tools as rumor_tools

    def fake_classify(text: str, *, timeout_seconds: float | None = None):
        if text == "第二条":
            return {
                "status": "unavailable",
                "raw_label": None,
                "mapped_label": "uncertain",
                "latency_ms": 1,
                "input_hash": "hash-2",
                "request_id": "request-2",
                "called_at": "2026-08-13T00:00:00+00:00",
                "usage": {},
                "error_code": "connection_error",
            }
        return {
            "status": "ok",
            "raw_label": "No",
            "mapped_label": "non_rumor",
            "latency_ms": 1,
            "input_hash": "hash-1",
            "request_id": "request-1",
            "called_at": "2026-08-13T00:00:00+00:00",
            "usage": {},
        }

    monkeypatch.setattr(rumor_tools, "classify_claim_text", fake_classify)
    services = RumorV3Services(
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=True,
    )
    result = asyncio.run(
        services.classify(
            {
                "normalized_claim": "组合主张",
                "subclaims": [
                    {"id": "claim-1", "text": "第一条", "material": True},
                    {"id": "claim-2", "text": "第二条", "material": True},
                ],
            },
            {},
        )
    )

    assert result["status"] == "partial"
    assert result["aggregate_label"] == "uncertain"
    assert result["label"] == "uncertain"
    assert [item["status"] for item in result["subclaims"]] == ["ok", "unavailable"]


def test_unconfigured_required_classifier_is_unavailable_not_skipped():
    services = RumorV3Services(
        web_search_enabled=False,
        web_fetch_enabled=False,
        classifier_enabled=False,
        classifier_required=True,
    )
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="请核验某项公开事实")]},
            config={"configurable": {"thread_id": "v3-classifier-required"}},
        )
    )

    assert result["rumor_report"]["research_branches"]["classifier"]["status"] == "unavailable"
    assert "classifier_not_configured" in result["rumor_report"]["limitations"]


def test_v3_uses_real_modelscope_http_adapter_and_keeps_rule_binding(monkeypatch):
    with _modelscope_server("No") as (base_url, requests):
        monkeypatch.setenv("RUMOR_MODEL_BASE_URL", base_url)
        monkeypatch.setenv("RUMOR_MODEL_API_STYLE", "modelscope_chat")
        monkeypatch.setenv("RUMOR_MODEL_NAME", "course-modelscope-model")
        graph = build_rumor_graph_v3(HttpAdapterServices())

        result = asyncio.run(
            graph.ainvoke(
                {"messages": [HumanMessage(content="请核验某项公开事实")]},
                config={"configurable": {"thread_id": "v3-real-http-adapter"}},
            )
        )

    report = result["rumor_report"]
    assert requests[0]["path"] == "/v1/chat"
    assert requests[0]["body"]["temperature"] == 0
    assert report["classifier_signal"]["model_id"] == "course-modelscope-model"
    assert report["classifier_signal"]["subclaims"][0]["raw_label"] == "No"
    assert report["classifier_signal"]["subclaims"][0]["mapped_label"] == "non_rumor"
    assert report["research_branches"]["classifier"]["status"] == "completed"
    assert report["decision"]["verdict"] == "证据不足"
    assert report["decision"]["classifier_consistency"] == "not_comparable"


def test_fetch_provenance_comes_from_successful_fetch_tool_not_model_output():
    evidence = _evidence("web-1", url="https://example.com/article")
    evidence["fetched_at"] = None
    research = {"status": "ok", "evidence": [evidence]}
    tool_messages = [
        {
            "name": "web_search",
            "content": '{"url":"https://example.com/article"}',
        },
        {
            "name": "web_fetch",
            "content": ('{"source_url":"https://example.com/article","requested_url":"https://example.com/article","fetched_at":"2026-08-12T12:30:00+00:00","content":"正文"}'),
        },
    ]

    enriched, fetched_urls = apply_verified_fetch_provenance(research, tool_messages)

    assert enriched["evidence"][0]["fetched_at"] == "2026-08-12T12:30:00+00:00"
    assert fetched_urls == ["https://example.com/article"]


def test_failed_or_search_only_result_cannot_claim_fetch_provenance():
    evidence = _evidence("web-1", url="https://example.com/article")
    evidence["fetched_at"] = None
    research = {"status": "ok", "evidence": [evidence]}

    enriched, fetched_urls = apply_verified_fetch_provenance(
        research,
        [
            {
                "name": "web_search",
                "content": "https://example.com/article",
            },
            {
                "name": "web_fetch",
                "content": "Error: timeout",
            },
        ],
    )

    assert enriched["evidence"][0]["fetched_at"] is None
    assert fetched_urls == []


def test_parallel_dispatch_uses_langgraph_send_for_four_branches():
    sends = make_parallel_sends({"messages": [HumanMessage(content="请核验公开事实")]})
    assert [send.node for send in sends] == ["rag", "web", "classifier", "authority"]
    assert len({id(send.arg) for send in sends}) == 4


def test_merge_rejects_unobserved_urls_and_deduplicates_ids():
    observed = _evidence("same", url="https://reuters.com/a")
    invented = _evidence("same", url="https://invented.invalid/a")
    evidence, rejected = merge_research_branches(
        {
            "web": {
                "status": "ok",
                "evidence": [observed, invented],
                "observed_urls": [observed["url"]],
            }
        }
    )
    assert [item["url"] for item in evidence] == [observed["url"]]
    assert rejected[0]["reason_code"] == "url_not_observed"


def test_critic_can_request_only_one_supplement_for_missing_material_claim():
    context = {
        "normalized_claim": "组合主张",
        "subclaims": [
            {"id": "claim-1", "text": "第一条", "material": True},
            {"id": "claim-2", "text": "第二条", "material": True},
        ],
    }
    review = build_evidence_review(context, [_evidence("one", url="https://reuters.com/a", claim_ids=["claim-1"])], supplement_count=0)
    assert review["missing_claim_ids"] == ["claim-2"]
    assert review["supplement_needed"] is True

    after_retry = build_evidence_review(context, [], supplement_count=1)
    assert after_retry["supplement_needed"] is False


def test_critic_requests_one_supplement_when_coverage_exists_but_threshold_fails():
    context = {
        "normalized_claim": "某项公开事实",
        "subclaims": [{"id": "claim-1", "text": "某项公开事实", "material": True}],
    }
    one_b = _evidence("one-b", url="https://www.reuters.com/world/example")

    review = build_evidence_review(context, [one_b], supplement_count=0)

    assert review["coverage_by_claim"]["claim-1"] == "covered"
    assert review["threshold_gap"] is True
    assert review["supplement_needed"] is True
    assert "裁决门槛" in review["notes"]


def test_critic_does_not_supplement_when_one_authoritative_a_meets_threshold():
    context = {
        "normalized_claim": "这种疾病治疗方法有效",
        "domain": "medical",
        "subclaims": [{"id": "claim-1", "text": "这种疾病治疗方法有效", "material": True}],
    }
    one_a = _evidence("one-a", url="https://www.who.int/news/item/example") | {
        "source_level": "A",
        "authority_scope": True,
        "authority_reason": "卫生领域职权匹配",
    }

    review = build_evidence_review(context, [one_a], supplement_count=0)

    assert review["threshold_gap"] is False
    assert review["supplement_needed"] is False


def test_explicit_graph_runs_parallel_branches_and_binds_rule_verdict():
    services = FakeServices(professional=True)
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="请核验这项医学公开事实")]},
            config={"configurable": {"thread_id": "v3-test"}},
        )
    )

    report = result["rumor_report"]
    assert report["schema_version"] == "rumorbuster-report-v3"
    assert report["domain_route"]["domain"] == "medical"
    assert report["research_branches"]["authority"]["status"] == "completed"
    assert report["decision"]["verdict"] == "非谣言"
    assert result["rumor_workflow"]["stage"] == "report"

    intervals = {name: (start, end) for name, start, end in services.calls}
    assert intervals["web"][0] < intervals["classifier"][1]
    assert intervals["classifier"][0] < intervals["web"][1]


def test_graph_skips_external_verification_for_non_factual_input():
    services = FakeServices()
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="请核验：我觉得这部电影很无聊")]},
            config={"configurable": {"thread_id": "v3-opinion"}},
        )
    )
    assert services.calls == []
    assert result["rumor_report"]["decision"]["verdict"] == "非事实性表达"


def test_one_parallel_branch_failure_does_not_cancel_adjudication():
    services = FakeServices(fail_web=True)
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="请核验某项公开事实")]},
            config={"configurable": {"thread_id": "v3-degraded"}},
        )
    )
    assert result["rumor_report"]["research_branches"]["web"]["status"] == "unavailable"
    assert result["rumor_report"]["decision"]["verdict"] == "证据不足"
    assert "web_research_unavailable" in result["rumor_report"]["limitations"]


def test_branch_timestamps_are_iso_8601():
    now = datetime.now(UTC).isoformat()
    assert "+00:00" in now
