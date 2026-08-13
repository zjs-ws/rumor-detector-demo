"""Small, transparent TF-IDF retriever for reviewed rumor records."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain.tools import tool

from deerflow.agents.rumor_agent.schemas import KnowledgeRetrievalResult, RagMatch

_DATA_PATH = Path(__file__).with_name("data") / "verified_rumors.jsonl"
_DEFAULT_THRESHOLD = 0.35


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())


def _char_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> Counter[str]:
    normalized = _normalize(text)
    grams: Counter[str] = Counter()
    for n in range(min_n, max_n + 1):
        grams.update(normalized[index : index + n] for index in range(max(0, len(normalized) - n + 1)))
    return grams


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


@lru_cache(maxsize=1)
def _load_index() -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, float]]]:
    records: list[dict[str, Any]] = []
    with _DATA_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("review_status") != "reviewed":
                continue
            records.append(record)

    documents = [_char_ngrams(" ".join([record["canonical_claim"], *record.get("variants", [])])) for record in records]
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.keys())
    count = max(1, len(documents))
    idf = {term: math.log((1 + count) / (1 + frequency)) + 1 for term, frequency in document_frequency.items()}
    vectors = [_tfidf(document, idf) for document in documents]
    return records, idf, vectors


def _tfidf(counts: Counter[str], idf: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    return {term: (frequency / total) * idf.get(term, 0.0) for term, frequency in counts.items()}


def retrieve_verified_rumors(
    claim: str,
    *,
    top_k: int = 3,
    threshold: float = _DEFAULT_THRESHOLD,
) -> KnowledgeRetrievalResult:
    records, idf, vectors = _load_index()
    query_vector = _tfidf(_char_ngrams(claim), idf)
    ranked: list[tuple[float, dict[str, Any], str]] = []
    for record, vector in zip(records, vectors, strict=True):
        score = _cosine(query_vector, vector)
        candidates = [record["canonical_claim"], *record.get("variants", [])]
        matched_variant = max(
            candidates,
            key=lambda value: _cosine(query_vector, _tfidf(_char_ngrams(value), idf)),
        )
        if score >= threshold:
            ranked.append((score, record, matched_variant))
    ranked.sort(key=lambda item: item[0], reverse=True)

    matches = [
        RagMatch(
            record_id=record["id"],
            canonical_claim=record["canonical_claim"],
            similarity=round(score, 4),
            matched_variant=matched_variant,
            historical_verdict=record["verdict"],
            authoritative_sources=[source["url"] for source in record.get("authoritative_sources", [])],
            event_date=record.get("event_date"),
            temporal_warning=record.get("temporal_warning"),
        )
        for score, record, matched_variant in ranked[: max(1, min(top_k, 10))]
    ]
    return KnowledgeRetrievalResult(
        status="ok" if matches else "no_match",
        query=claim,
        matches=matches,
        threshold=threshold,
    )


@tool("retrieve_verified_rumors")
def retrieve_verified_rumors_tool(claim: str, top_k: int = 3, threshold: float = 0.05) -> str:
    """Retrieve reviewed historical rumor records similar to a claim.

    A match is non-authoritative and never decides the current verdict by
    itself. Current names, places, dates and quantities still require external
    verification.

    Args:
        claim: The normalized factual claim.
        top_k: Number of matches to return, from 1 to 10.
        threshold: Minimum cosine similarity, locked to 0.05 by the workflow.
    """
    safe_threshold = max(0.0, min(float(threshold), 1.0))
    return retrieve_verified_rumors(claim, top_k=top_k, threshold=safe_threshold).model_dump_json()


__all__ = ["retrieve_verified_rumors", "retrieve_verified_rumors_tool"]
