"""Decision-table tests for RumorBuster's deterministic evidence policy."""

from deerflow.agents.rumor_agent.evidence import decide_evidence


def _evidence(
    evidence_id: str,
    *,
    stance: str,
    level: str,
    url: str,
    group: str,
    authority_scope: bool = False,
    directness: str = "direct",
    temporal_relevance: str = "current",
    provenance: str = "web",
):
    return {
        "id": evidence_id,
        "title": evidence_id,
        "url": url,
        "publisher": group,
        "stance": stance,
        "source_level": level,
        "directness": directness,
        "authority_scope": authority_scope,
        "independent_group": group,
        "temporal_relevance": temporal_relevance,
        "fetched_at": "2026-08-12T00:00:00+08:00",
        "summary": "直接说明待核验事项",
        "provenance": provenance,
    }


def test_one_scope_matched_a_source_can_refute_claim():
    item = _evidence(
        "a-1",
        stance="refute",
        level="A",
        url="https://authority.example/notice",
        group="authority",
        authority_scope=True,
    )
    decision = decide_evidence(evidence=[item], allowed_urls={item["url"]})

    assert decision.verdict == "谣言"
    assert decision.strength == "high"
    assert decision.accepted_evidence_ids == ["a-1"]


def test_ipcc_is_code_verified_as_scope_matched_a_for_climate_claim():
    item = _evidence(
        "ipcc-a",
        stance="support",
        level="C",
        url="https://www.ipcc.ch/2021/08/09/ar6-wg1-20210809-pr/",
        group="IPCC",
    )
    item["published_at"] = "2021-08-09"
    item["claim_ids"] = ["claim-1"]
    decision = decide_evidence(
        evidence=[item],
        allowed_urls={item["url"]},
        claim_context={
            "normalized_claim": "科学证据表明全球气候正在变暖",
            "subclaims": [{"id": "claim-1", "text": "全球气候正在变暖", "material": True}],
            "temporality": "timeless",
            "domain": "science",
        },
    )

    assert decision.verdict == "非谣言"
    assert decision.accepted_evidence_ids == ["ipcc-a"]


def test_runtime_web_evidence_requires_verified_fetch_timestamp():
    item = _evidence(
        "b-runtime",
        stance="support",
        level="B",
        url="https://media.example/report",
        group="media",
    )
    item.pop("fetched_at")
    rejected = decide_evidence(evidence=[item], allowed_urls={item["url"]})
    assert rejected.excluded_evidence[0].reason_code == "fetch_not_verified"

    item["fetched_at"] = "2026-08-12T10:00:00+08:00"
    accepted_for_threshold = decide_evidence(evidence=[item], allowed_urls={item["url"]})
    assert all(excluded.reason_code != "fetch_not_verified" for excluded in accepted_for_threshold.excluded_evidence)


def test_two_independent_direct_b_sources_are_required():
    first = _evidence(
        "b-1",
        stance="support",
        level="B",
        url="https://media-one.example/report",
        group="media-one",
    )
    duplicate = _evidence(
        "b-2",
        stance="support",
        level="B",
        url="https://mirror.example/repost",
        group="media-one",
    )
    second = _evidence(
        "b-3",
        stance="support",
        level="B",
        url="https://media-two.example/report",
        group="media-two",
    )
    second["summary"] = "独立获得并核验另一份原始文件"

    insufficient = decide_evidence(evidence=[first, duplicate])
    sufficient = decide_evidence(evidence=[first, duplicate, second])

    assert insufficient.verdict == "证据不足"
    assert sufficient.verdict == "非谣言"
    assert sufficient.accepted_evidence_ids == ["b-1", "b-3"]


def test_a_against_a_is_disputed_and_classifier_cannot_override():
    support = _evidence(
        "support-a",
        stance="support",
        level="A",
        url="https://agency-one.example/notice",
        group="agency-one",
        authority_scope=True,
    )
    refute = _evidence(
        "refute-a",
        stance="refute",
        level="A",
        url="https://agency-two.example/notice",
        group="agency-two",
        authority_scope=True,
    )

    decision = decide_evidence(
        evidence=[support, refute],
        classifier_signal={"status": "ok", "label": "rumor", "authoritative": False},
    )

    assert decision.verdict == "存疑"
    assert decision.classifier_consistency == "not_comparable"


def test_classifier_consistency_is_calculated_per_subclaim_without_changing_verdict():
    support = _evidence(
        "support-a",
        stance="support",
        level="A",
        url="https://agency-one.example/notice",
        group="agency-one",
        authority_scope=True,
    )
    support["claim_ids"] = ["claim-1"]
    refute = _evidence(
        "refute-a",
        stance="refute",
        level="A",
        url="https://agency-two.example/notice",
        group="agency-two",
        authority_scope=True,
    )
    refute["claim_ids"] = ["claim-2"]

    decision = decide_evidence(
        evidence=[support, refute],
        claim_context={
            "normalized_claim": "两个事实组合",
            "subclaims": [
                {"id": "claim-1", "text": "第一条", "material": True},
                {"id": "claim-2", "text": "第二条", "material": True},
            ],
        },
        classifier_signal={
            "status": "ok",
            "label": "uncertain",
            "aggregate_label": "uncertain",
            "authoritative": False,
            "subclaims": [
                {
                    "claim_id": "claim-1",
                    "text": "第一条",
                    "status": "ok",
                    "raw_label": "No",
                    "mapped_label": "non_rumor",
                },
                {
                    "claim_id": "claim-2",
                    "text": "第二条",
                    "status": "ok",
                    "raw_label": "No",
                    "mapped_label": "non_rumor",
                },
            ],
        },
    )

    assert decision.verdict == "误导"
    assert decision.classifier_consistency == "conflict"
    assert decision.classifier_consistency_by_claim == {
        "claim-1": "consistent",
        "claim-2": "conflict",
    }


def test_invalid_classifier_label_is_never_treated_as_non_rumor():
    item = _evidence(
        "support-a",
        stance="support",
        level="A",
        url="https://authority.example/notice",
        group="authority",
        authority_scope=True,
    )
    item["claim_ids"] = ["claim-1"]

    decision = decide_evidence(
        evidence=[item],
        claim_context={
            "normalized_claim": "某项公开事实",
            "subclaims": [{"id": "claim-1", "text": "某项公开事实", "material": True}],
        },
        classifier_signal={
            "status": "ok",
            "label": "mixed",
            "authoritative": False,
        },
    )

    assert decision.verdict == "非谣言"
    assert decision.classifier_consistency != "consistent"


def test_a_source_outweighs_opposing_b_sources_for_the_same_claim():
    support_a = _evidence(
        "support-a",
        stance="support",
        level="A",
        url="https://authority.example/notice",
        group="authority",
        authority_scope=True,
    )
    refute_b1 = _evidence(
        "refute-b1",
        stance="refute",
        level="B",
        url="https://media-one.example/report",
        group="media-one",
    )
    refute_b2 = _evidence(
        "refute-b2",
        stance="refute",
        level="B",
        url="https://media-two.example/report",
        group="media-two",
    )

    decision = decide_evidence(evidence=[support_a, refute_b1, refute_b2])
    assert decision.verdict == "非谣言"
    assert decision.accepted_evidence_ids == ["support-a"]


def test_snippets_stale_pages_rag_and_unobserved_urls_are_excluded():
    evidence = [
        _evidence("snippet", stance="refute", level="A", url="https://a.example/1", group="a", authority_scope=True, directness="snippet_only"),
        _evidence("stale", stance="refute", level="A", url="https://a.example/2", group="a", authority_scope=True, temporal_relevance="stale"),
        _evidence("rag", stance="refute", level="A", url="https://a.example/3", group="a", authority_scope=True, provenance="knowledge_base"),
        _evidence("invented", stance="refute", level="A", url="https://invented.example/4", group="a", authority_scope=True),
    ]

    decision = decide_evidence(
        evidence=evidence,
        allowed_urls={"https://a.example/1", "https://a.example/2", "https://a.example/3"},
    )

    assert decision.verdict == "证据不足"
    assert {item.reason_code for item in decision.excluded_evidence} == {
        "not_direct",
        "stale",
        "rag_not_authoritative",
        "url_not_observed",
    }
