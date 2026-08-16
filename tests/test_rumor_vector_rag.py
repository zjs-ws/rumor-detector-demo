"""Contracts for the course-aligned local vector RAG layer."""

from __future__ import annotations

import json

import pytest
from langchain_core.documents import Document

from deerflow.agents.rumor_agent.rag import (
    _load_extra_documents,
    _merge_ranked_matches,
    format_rag_context,
    is_high_confidence_rag_match,
    load_rag_documents,
    retrieve_rumor_knowledge,
    split_rag_documents,
    validate_rag_documents,
)
from deerflow.agents.rumor_agent.schemas import KnowledgeRetrievalResult, RagMatch


def _match(record_id: str, *, dense: float | None = None, sparse: float | None = None) -> RagMatch:
    return RagMatch(
        record_id=record_id,
        document_id=record_id,
        chunk_id=f"{record_id}#chunk-1" if dense is not None else "",
        canonical_claim=f"主张{record_id}",
        similarity=max(dense or 0, sparse or 0),
        dense_similarity=dense,
        sparse_similarity=sparse,
        matched_variant=f"变体{record_id}",
        historical_verdict="rumor",
        retrieval_sources=["dense"] if dense is not None else ["sparse"],
    )


def test_reviewed_seed_records_are_langchain_documents():
    documents = load_rag_documents()

    assert len(documents) >= 30
    assert all(document.metadata["review_status"] == "reviewed" for document in documents)
    assert any("核查主张：饮酒可以预防新冠肺炎" in document.page_content for document in documents)


def test_chinese_splitter_preserves_traceable_chunk_metadata():
    document = Document(
        page_content="第一段。" * 40,
        metadata={"document_id": "doc-1", "record_id": "record-1", "review_status": "reviewed"},
    )

    chunks = split_rag_documents([document], chunk_size=60, chunk_overlap=10)

    assert len(chunks) > 1
    assert chunks[0].metadata["chunk_id"] == "doc-1#chunk-1"
    assert all(chunk.metadata["chunk_count"] == len(chunks) for chunk in chunks)


def test_unreviewed_extra_document_is_not_loaded(tmp_path):
    document = tmp_path / "sample.md"
    document.write_text("公开核查内容", encoding="utf-8")
    document.with_suffix(".md.meta.json").write_text(
        json.dumps({"document_id": "sample", "review_status": "draft"}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert _load_extra_documents(tmp_path) == []


def test_reviewed_document_without_traceable_source_is_rejected():
    document = Document(
        page_content="已复核正文",
        metadata={
            "document_id": "missing-source",
            "publisher": "发布主体",
            "reviewed_at": "2026-08-14",
            "review_status": "reviewed",
        },
    )

    with pytest.raises(ValueError, match=r"公开HTTP\(S\)来源"):
        validate_rag_documents([document])


def test_rrf_merges_dense_and_sparse_versions_of_same_record():
    merged = _merge_ranked_matches(
        [_match("same", dense=0.82), _match("dense-only", dense=0.7)],
        [_match("same", sparse=0.6), _match("sparse-only", sparse=0.5)],
        top_k=3,
    )

    assert merged[0].record_id == "same"
    assert merged[0].dense_similarity == 0.82
    assert merged[0].sparse_similarity == 0.6
    assert merged[0].retrieval_sources == ["dense", "sparse"]
    assert merged[0].fusion_score is not None


def test_post_filter_rejects_nearest_neighbour_noise_but_keeps_correlated_match():
    unrelated = _match("unrelated", dense=0.52, sparse=0.07)
    exact_like = _match("exact", dense=0.66, sparse=0.50)

    assert is_high_confidence_rag_match(unrelated) is False
    assert is_high_confidence_rag_match(exact_like) is True


def test_missing_dense_index_degrades_to_sparse_without_failing(tmp_path):
    result = retrieve_rumor_knowledge("喝高度酒能防新冠", persist_dir=tmp_path)

    assert result.status == "partial"
    assert result.retrieval_mode == "sparse_fallback"
    assert result.matches[0].record_id == "who-covid-007"
    assert "rag_index_missing" in result.degradation_codes


def test_stale_corpus_manifest_degrades_instead_of_loading_index(tmp_path):
    target = tmp_path / "indexes" / "stale-version"
    target.mkdir(parents=True)
    (tmp_path / "current.json").write_text('{"index_version":"stale-version"}', encoding="utf-8")
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "rumorbuster-rag-v2",
                "index_version": "stale-version",
                "embedding_model": "GanymedeNil/text2vec-large-chinese",
                "chunk_size": 500,
                "chunk_overlap": 80,
                "corpus_sha256": "outdated",
            }
        ),
        encoding="utf-8",
    )

    result = retrieve_rumor_knowledge("喝高度酒能防新冠", persist_dir=tmp_path)

    assert result.retrieval_mode == "sparse_fallback"
    assert "rag_index_mismatch" in result.degradation_codes


def test_rag_context_is_bounded_and_explicitly_traceable():
    result = KnowledgeRetrievalResult(
        status="ok",
        query="测试",
        threshold=0.05,
        matches=[
            _match("doc-1", dense=0.9).model_copy(
                update={
                    "excerpt": "历史核查片段",
                    "publisher": "权威机构",
                    "source_url": "https://example.org/fact-check",
                    "reviewed_at": "2026-08-14",
                }
            )
        ],
    )

    context = format_rag_context(result)

    assert "[KB:doc-1#chunk-1]" in context
    assert "历史核查片段" in context
    assert "https://example.org/fact-check" in context
