"""Contract tests for RumorBuster's explicit V3 StateGraph."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_core.messages import HumanMessage

import deerflow.agents.rumor_agent.graph_v3 as graph_v3_module
from deerflow.agents.rumor_agent.graph_v3 import (
    RumorV3Services,
    _claim_candidate,
    _select_verbatim_excerpt,
    apply_verified_fetch_provenance,
    build_evidence_review,
    build_rumor_graph_v3,
    detect_claim_domain,
    detect_verification_intent,
    make_parallel_sends,
    merge_research_branches,
    parse_claim_context_response,
    repair_claim_context,
    rescue_unverified_evidence,
    sanitize_text_risk_analysis,
)
from deerflow.agents.rumor_agent.research_plan import build_research_plan
from deerflow.agents.rumor_agent.schemas import ClaimContext, KnowledgeRetrievalResult, Subclaim


@pytest.fixture(autouse=True)
def _disable_rescue_in_graph_tests(monkeypatch):
    """Graph-level tests must never issue real rescue fetches."""

    async def _noop(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(graph_v3_module, "rescue_unverified_evidence", _noop)


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
        "excerpt": f"{evidence_id}正文证据",
        "document_hash": "a" * 64,
        "fetch_status": "fetched",
        "fetch_attempts": [{"url": url, "status": "fetched"}],
        "provenance": "web",
    }


class FakeServices(RumorV3Services):
    def __init__(self, *, professional: bool = False, fail_web: bool = False, fail_rag: bool = False):
        super().__init__(
            web_search_enabled=True,
            web_fetch_enabled=True,
            classifier_enabled=True,
            timeline_enabled=True,
        )
        self.professional = professional
        self.fail_web = fail_web
        self.fail_rag = fail_rag
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
        if self.fail_rag:
            raise TimeoutError("rag timeout")
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

    async def research_timeline(self, claim_context, config):
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.03)
        finished = asyncio.get_running_loop().time()
        self.calls.append(("timeline_research", started, finished))
        items = []
        for index, event_type in enumerate(("spread", "mutation", "correction"), start=1):
            item = _evidence(
                f"timeline-{index}",
                url=f"https://timeline-{index}.example/article",
            ) | {
                "published_at": f"2026-08-{9 + index:02d}",
                "stance": "context",
                "source_level": "C",
                "timeline_only": True,
                "timeline_event_type": event_type,
                "claim_variant": f"传播版本{index}",
                "change_summary": "传播表述发生变化" if index == 2 else "",
            }
            items.append(item)
        return {
            "status": "ok",
            "evidence": items,
            "rejected_evidence": [],
            "observed_urls": [item["url"] for item in items],
            "notes": "",
        }

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
    assert detect_claim_domain("榴莲不能吃，被人浸黄色药水的有害")[0] == "medical"
    assert detect_claim_domain("根据刑法和最高法司法解释")[0] == "legal"
    assert detect_claim_domain("证监会发布上市公司监管公告")[0] == "finance"
    assert detect_claim_domain("某地今天下雨")[0] == "general"
    assert detect_claim_domain("管道疏通剂中的强碱遇热水会剧烈放热")[0] == "science"


def test_compound_cleaner_claim_is_split_and_question_suffix_removed():
    context = repair_claim_context(
        ClaimContext(
            normalized_claim="疏通剂，洁厕灵等强碱类的一律不能碰热水，可能爆射让人毁容这是谣言吗",
            subclaims=[
                Subclaim(
                    id="claim-1",
                    text="疏通剂，洁厕灵等强碱类的一律不能碰热水，可能爆射让人毁容这是谣言吗",
                )
            ],
        )
    )

    assert context.normalized_claim.endswith("毁容")
    assert context.domain.value == "science"
    assert [item.id for item in context.subclaims] == ["claim-1", "claim-2"]
    assert "热水" in context.subclaims[0].text
    assert context.subclaims[1].text == "洁厕灵属于强碱类清洁剂"


def test_historical_markers_override_medical_domain_words():
    tuskegee = repair_claim_context(
        ClaimContext(
            normalized_claim="美国政府曾让患梅毒的人长期得不到正常治疗，以观察疾病发展",
            subclaims=[Subclaim(id="claim-1", text="美国政府曾实施未治疗梅毒研究")],
            temporality="unknown",
            domain="medical",
        )
    )
    mkultra = repair_claim_context(
        ClaimContext(
            normalized_claim="CIA秘密拿普通人做精神控制和致幻药物实验",
            subclaims=[Subclaim(id="claim-1", text="CIA实施MKULTRA药物实验")],
            temporality="unknown",
            domain="science",
        )
    )

    assert tuskegee.temporality.value == "event_bound"
    assert tuskegee.temporality_basis == "historical_marker"
    assert mkultra.temporality.value == "event_bound"
    assert mkultra.temporality_basis == "historical_marker"


def test_domain_words_alone_do_not_turn_unknown_claim_into_current_status():
    context = repair_claim_context(
        ClaimContext(
            normalized_claim="某机构进行药物治疗实验",
            subclaims=[Subclaim(id="claim-1", text="某机构进行药物治疗实验")],
            temporality="unknown",
        )
    )
    assert context.temporality.value == "general"
    assert context.temporality_basis == "no_temporal_marker"


def test_markerless_model_current_status_is_downgraded_to_general():
    context = repair_claim_context(
        ClaimContext(
            normalized_claim="抽烟有害身体健康",
            subclaims=[Subclaim(id="claim-1", text="抽烟有害身体健康")],
            temporality="current_status",
            temporality_basis="model",
        )
    )
    assert context.temporality.value == "general"
    assert context.temporality_basis == "model_current_status_overridden"


def test_current_marker_keeps_current_status():
    context = repair_claim_context(
        ClaimContext(
            normalized_claim="目前该政策仍然有效",
            subclaims=[Subclaim(id="claim-1", text="目前该政策仍然有效")],
            temporality="current_status",
        )
    )
    assert context.temporality.value == "current_status"
    assert context.temporality_basis == "current_marker"


def test_model_timeless_and_event_bound_are_kept():
    timeless = repair_claim_context(
        ClaimContext(
            normalized_claim="吸烟增加患肺癌的风险",
            subclaims=[Subclaim(id="claim-1", text="吸烟增加患肺癌的风险")],
            temporality="timeless",
            temporality_basis="model",
        )
    )
    event_bound = repair_claim_context(
        ClaimContext(
            normalized_claim="某机构开展某实验",
            subclaims=[Subclaim(id="claim-1", text="某机构开展某实验")],
            temporality="event_bound",
            temporality_basis="model",
        )
    )
    assert timeless.temporality.value == "timeless"
    assert event_bound.temporality.value == "event_bound"


def test_research_plan_routes_known_entities_to_locked_authority_queries():
    tuskegee = build_research_plan(
        {
            "normalized_claim": "美国公共卫生署曾开展塔斯基吉梅毒研究",
            "subclaims": [{"id": "claim-1", "text": "美国公共卫生署开展塔斯基吉研究"}],
            "temporality": "event_bound",
            "domain": "medical",
        }
    )
    mkultra = build_research_plan(
        {
            "normalized_claim": "CIA曾开展MKULTRA致幻药物实验",
            "subclaims": [{"id": "claim-1", "text": "CIA开展MKULTRA"}],
            "temporality": "event_bound",
            "domain": "science",
        }
    )
    nasa = build_research_plan(
        {
            "normalized_claim": "NASA发现历史上凭空少了一天",
            "subclaims": [{"id": "claim-1", "text": "NASA发现少了一天"}],
            "domain": "science",
        }
    )
    unknown_general = build_research_plan(
        {
            "normalized_claim": "某项没有明确机构的公开事实",
            "subclaims": [{"id": "claim-1", "text": "某项公开事实"}],
            "domain": "general",
        }
    )

    assert "site:cdc.gov" in tuskegee["queries"]["authority"]
    assert "Tuskegee" in tuskegee["queries"]["authority"]
    assert "site:cia.gov" in mkultra["queries"]["authority"]
    assert "MKULTRA" in mkultra["queries"]["authority"]
    assert "site:nasa.gov" in nasa["queries"]["authority"]
    assert "missing day" in nasa["queries"]["authority"]
    assert unknown_general["queries"]["authority"] == ""


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
    assert context["temporality"] == "general"
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
    evidence["excerpt"] = "正文"
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
    assert enriched["evidence"][0]["fetch_status"] == "fetched"
    assert enriched["evidence"][0]["extraction_status"] == "ok"
    assert enriched["evidence"][0]["document_hash"]
    assert fetched_urls == ["https://example.com/article"]


def test_fetch_provenance_downgrades_unverified_or_irrelevant_excerpt():
    evidence = _evidence("nasa", url="https://science.nasa.gov/unrelated") | {
        "stance": "refute",
        "excerpt": "NGC 4372 is a distant star cluster.",
        "summary": "该页面未提及NASA发现少了一天",
    }
    research = {"status": "ok", "evidence": [evidence]}
    messages = [
        {
            "name": "web_fetch",
            "content": json.dumps(
                {
                    "source_url": evidence["url"],
                    "requested_url": evidence["url"],
                    "fetched_at": "2026-08-14T00:00:00+00:00",
                    "content": "NGC 4372 is a distant star cluster.",
                }
            ),
        }
    ]

    enriched, _ = apply_verified_fetch_provenance(
        research,
        messages,
        relevance_terms=["missing day", "lost day", "少了一天"],
    )

    assert enriched["evidence"][0]["directness"] == "indirect"
    assert enriched["evidence"][0]["extraction_status"] == "absence_only"


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


def test_parallel_dispatch_uses_langgraph_send_for_five_branches():
    sends = make_parallel_sends({"messages": [HumanMessage(content="请核验公开事实")]})
    assert [send.node for send in sends] == ["rag", "web", "classifier", "authority", "timeline_research"]
    assert len({id(send.arg) for send in sends}) == 5


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


def test_timeline_branch_is_code_locked_out_of_adjudication():
    item = _evidence("timeline-1", url="https://timeline.example/one")
    evidence, rejected = merge_research_branches(
        {
            "timeline": {
                "status": "ok",
                "evidence": [item],
                "observed_urls": [item["url"]],
            }
        }
    )

    assert rejected == []
    assert evidence[0]["timeline_only"] is True
    assert evidence[0]["stance"] == "context"


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


def test_critic_does_not_claim_coverage_from_snippets_or_timeline_material():
    context = {
        "normalized_claim": "榴莲被黄色药水浸泡后有害",
        "subclaims": [{"id": "claim-1", "text": "榴莲被黄色药水浸泡后有害", "material": True}],
    }
    snippet = _evidence("snippet", url="https://www.samr.gov.cn/example") | {
        "directness": "snippet_only",
        "extraction_status": "snippet_only",
    }
    timeline = _evidence("timeline", url="https://example.com/timeline") | {
        "timeline_only": True,
        "stance": "context",
    }

    review = build_evidence_review(context, [snippet, timeline], supplement_count=0)

    assert review["coverage_by_claim"]["claim-1"] == "missing"
    assert review["missing_claim_ids"] == ["claim-1"]
    assert review["supplement_needed"] is True


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
    assert report["research_branches"]["timeline_research"]["status"] == "completed"
    assert report["decision"]["verdict"] == "非谣言"
    assert report["timeline"]["timeline_status"] == "ready"
    assert len(report["timeline"]["events"]) >= 3
    propagation_events = [
        event for event in report["timeline"]["events"] if event["evidence_id"].startswith("timeline-")
    ]
    assert len(propagation_events) == 3
    assert all(not event["used_for_decision"] for event in propagation_events)
    assert result["rumor_workflow"]["stage"] == "report"

    intervals = {name: (start, end) for name, start, end in services.calls}
    assert intervals["web"][0] < intervals["classifier"][1]
    assert intervals["classifier"][0] < intervals["web"][1]


def test_declarative_fact_claim_does_not_require_verification_magic_words():
    is_verification, reason = detect_verification_intent(
        "榴莲不能吃，被人浸黄色药水的有害",
        source_url=None,
        initial_claim="榴莲不能吃，被人浸黄色药水的有害",
    )

    assert is_verification is True
    assert reason == "factual_assertion"


def test_declarative_fact_claim_enters_the_verification_graph():
    services = FakeServices()
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="榴莲不能吃，被人浸黄色药水的有害")]},
            config={"configurable": {"thread_id": "v3-bare-claim"}},
        )
    )

    assert result["rumor_workflow"]["routing_reason"] == "factual_assertion"
    assert result["rumor_report"]["schema_version"] == "rumorbuster-report-v3"
    assert any(name == "web" for name, _started, _finished in services.calls)


def test_clear_opinion_and_greeting_remain_conversational():
    opinion = detect_verification_intent(
        "我觉得榴莲的味道很难闻",
        source_url=None,
        initial_claim="我觉得榴莲的味道很难闻",
    )
    greeting = detect_verification_intent(
        "你好，你能做什么",
        source_url=None,
        initial_claim="你好，你能做什么",
    )

    assert opinion == (False, "personal_opinion")
    assert greeting == (False, "conversation_request")


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
    assert result["rumor_report"]["timeline"]["timeline_status"] == "ready"
    assert "web_research_unavailable" in result["rumor_report"]["limitations"]


def test_rag_failure_produces_a_schema_valid_degraded_report():
    services = FakeServices(fail_rag=True)
    graph = build_rumor_graph_v3(services)
    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="请核验某项公开事实")]},
            config={"configurable": {"thread_id": "v3-rag-degraded"}},
        )
    )

    rag = KnowledgeRetrievalResult.model_validate(result["rumor_report"]["rag"])
    assert rag.status == "unavailable"
    assert rag.query == "某项公开事实"
    assert rag.threshold == 0.0
    assert result["rumor_report"]["decision"]["verdict"] == "证据不足"
    assert "rag_unavailable" in result["rumor_report"]["limitations"]


def test_branch_timestamps_are_iso_8601():
    now = datetime.now(UTC).isoformat()
    assert "+00:00" in now


def _stub_rescue_tool(monkeypatch, url_results: dict[str, str]):
    class FakeTool:
        def __init__(self, results):
            self.results = results

        def invoke(self, args):
            return self.results.get(args["url"], "Error: unavailable in test")

    import deerflow.config as config_module
    import deerflow.reflection as reflection_module

    monkeypatch.setattr(
        config_module,
        "get_app_config",
        lambda: type("Config", (), {"get_tool_config": lambda _self, _name: type("ToolConfig", (), {"use": "fake:tool"})()})(),
    )
    monkeypatch.setattr(reflection_module, "resolve_variable", lambda _use: FakeTool(url_results))


def _rescue_claim() -> ClaimContext:
    return ClaimContext(
        normalized_claim="抽烟有害身体健康",
        subclaims=[Subclaim(id="claim-1", text="抽烟有害身体健康")],
    )


def test_select_verbatim_excerpt_picks_claim_related_sentence():
    content = "烟草使用导致多种疾病。吸烟危害健康是不争的医学结论。另有其他内容。"
    excerpt = _select_verbatim_excerpt(content, ["抽烟有害身体健康", "吸烟危害健康"])
    assert excerpt == "吸烟危害健康是不争的医学结论"


def test_select_verbatim_excerpt_rejects_unrelated_content():
    content = "今天天气晴朗。适合出门散步。"
    assert _select_verbatim_excerpt(content, ["抽烟有害身体健康", "吸烟有害"]) is None


def test_rescue_refetches_and_quotes_unverified_a_evidence(monkeypatch):
    content = "吸烟危害健康是不争的医学结论。烟草使用可导致多种恶性肿瘤。"
    _stub_rescue_tool(
        monkeypatch,
        {
            "https://www.nhc.gov.cn/a": json.dumps(
                {
                    "source_url": "https://www.nhc.gov.cn/a",
                    "fetched_at": "2026-08-17T00:00:00+00:00",
                    "content": content,
                }
            )
        },
    )
    item = _evidence("authority-1", url="https://www.nhc.gov.cn/a") | {
        "source_level": "A",
        "fetch_status": "not_fetched",
        "excerpt": "吸烟危害健康",
    }

    rescued = asyncio.run(
        rescue_unverified_evidence([item], _rescue_claim(), {"https://www.nhc.gov.cn/a"})
    )

    assert rescued == 1
    assert item["fetch_status"] == "fetched"
    assert item["extraction_status"] == "ok"
    assert item["document_hash"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert item["excerpt"] in content
    assert item["fetch_attempts"][0]["via"] == "deterministic_rescue"


def test_rescue_respects_two_fetch_budget(monkeypatch):
    content = "吸烟危害健康是不争的医学结论。"
    urls = {f"https://www.nhc.gov.cn/{index}": json.dumps({"source_url": f"https://www.nhc.gov.cn/{index}", "fetched_at": "2026-08-17T00:00:00+00:00", "content": content}) for index in range(3)}
    _stub_rescue_tool(monkeypatch, urls)
    items = [
        _evidence(f"a-{index}", url=url) | {"source_level": "A", "fetch_status": "not_fetched"}
        for index, url in enumerate(urls)
    ]

    rescued = asyncio.run(rescue_unverified_evidence(items, _rescue_claim(), set(urls)))

    assert rescued == 2
    assert sum(1 for item in items if item["fetch_status"] == "fetched") == 2


def test_rescue_skips_low_grade_and_unobserved_urls(monkeypatch):
    _stub_rescue_tool(
        monkeypatch,
        {
            "https://www.nhc.gov.cn/a": json.dumps(
                {"source_url": "https://www.nhc.gov.cn/a", "fetched_at": "2026-08-17T00:00:00+00:00", "content": "吸烟危害健康。"}
            )
        },
    )
    low_grade = _evidence("c-1", url="https://www.nhc.gov.cn/a") | {"source_level": "C", "fetch_status": "not_fetched"}
    unobserved = _evidence("a-1", url="https://www.nhc.gov.cn/unobserved") | {"source_level": "A", "fetch_status": "not_fetched"}

    rescued = asyncio.run(
        rescue_unverified_evidence([low_grade, unobserved], _rescue_claim(), {"https://www.nhc.gov.cn/a"})
    )

    assert rescued == 0
    assert low_grade["fetch_status"] == "not_fetched"
    assert unobserved["fetch_status"] == "not_fetched"


def test_rescue_skips_fetch_errors_and_empty_content(monkeypatch):
    _stub_rescue_tool(monkeypatch, {"https://www.nhc.gov.cn/a": "Error: blocked"})
    failing = _evidence("a-1", url="https://www.nhc.gov.cn/a") | {"source_level": "A", "fetch_status": "not_fetched"}

    rescued = asyncio.run(rescue_unverified_evidence([failing], _rescue_claim(), {"https://www.nhc.gov.cn/a"}))

    assert rescued == 0
    assert failing["fetch_status"] == "not_fetched"


def test_rescue_skips_already_verified_items(monkeypatch):
    _stub_rescue_tool(monkeypatch, {})
    verified = _evidence("a-1", url="https://www.nhc.gov.cn/a") | {"source_level": "A"}

    rescued = asyncio.run(rescue_unverified_evidence([verified], _rescue_claim(), {"https://www.nhc.gov.cn/a"}))

    assert rescued == 0


def test_rescue_repairs_fetched_item_with_unverified_excerpt(monkeypatch):
    content = "烟草使用导致多种疾病。吸烟危害健康是不争的医学结论。"
    _stub_rescue_tool(
        monkeypatch,
        {
            "https://www.nhc.gov.cn/a": json.dumps(
                {"source_url": "https://www.nhc.gov.cn/a", "fetched_at": "2026-08-17T00:00:00+00:00", "content": content}
            )
        },
    )
    item = _evidence("authority-1", url="https://www.nhc.gov.cn/a") | {
        "source_level": "A",
        "directness": "indirect",
        "extraction_status": "excerpt_unverified",
        "excerpt": "吸烟危害健康",
    }

    rescued = asyncio.run(rescue_unverified_evidence([item], _rescue_claim(), {"https://www.nhc.gov.cn/a"}))

    assert rescued == 1
    assert item["directness"] == "direct"
    assert item["extraction_status"] == "ok"
    assert item["excerpt"] in content


def test_rescue_skips_fetched_item_without_downgrade_marker(monkeypatch):
    _stub_rescue_tool(monkeypatch, {})
    model_indirect = _evidence("a-1", url="https://www.nhc.gov.cn/a") | {
        "source_level": "A",
        "directness": "indirect",
        "extraction_status": "ok",
    }

    rescued = asyncio.run(rescue_unverified_evidence([model_indirect], _rescue_claim(), {"https://www.nhc.gov.cn/a"}))

    assert rescued == 0


def test_rescue_retries_transient_fetch_failure(monkeypatch):
    import deerflow.config as config_module
    import deerflow.reflection as reflection_module

    content = "吸烟危害健康是不争的医学结论。"

    class FlakyTool:
        def __init__(self):
            self.calls = 0

        def invoke(self, args):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("transient TLS failure")
            return json.dumps({"source_url": args["url"], "fetched_at": "2026-08-17T00:00:00+00:00", "content": content})

    flaky = FlakyTool()
    monkeypatch.setattr(
        config_module,
        "get_app_config",
        lambda: type("Config", (), {"get_tool_config": lambda _self, _name: type("ToolConfig", (), {"use": "fake:tool"})()})(),
    )
    monkeypatch.setattr(reflection_module, "resolve_variable", lambda _use: flaky)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    item = _evidence("a-1", url="https://www.nhc.gov.cn/a") | {"source_level": "A", "fetch_status": "not_fetched"}
    rescued = asyncio.run(rescue_unverified_evidence([item], _rescue_claim(), {"https://www.nhc.gov.cn/a"}))

    assert flaky.calls == 2
    assert rescued == 1
    assert item["fetch_status"] == "fetched"
