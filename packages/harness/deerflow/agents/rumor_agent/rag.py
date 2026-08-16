"""Course-aligned local vector RAG with a transparent sparse fallback.

The checked-in reviewed rumor records remain the deterministic keyword
retriever.  A separately built Chroma index adds HuggingFace dense retrieval.
Neither result is authoritative evidence for the current claim.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from langchain.tools import tool
from langchain_core.documents import Document

from deerflow.agents.rumor_agent.schemas import KnowledgeRetrievalResult, RagMatch

_DATA_PATH = Path(__file__).with_name("data") / "verified_rumors.jsonl"
_DOCUMENTS_PATH = Path(__file__).with_name("data") / "rag_documents"
_DEFAULT_THRESHOLD = 0.35
_DEFAULT_SPARSE_THRESHOLD = 0.05
_DEFAULT_DENSE_THRESHOLD = 0.35
_DEFAULT_EMBEDDING_MODEL = "GanymedeNil/text2vec-large-chinese"
_INDEX_SCHEMA_VERSION = "rumorbuster-rag-v2"
_COLLECTION_NAME = "rumorbuster_verified_knowledge"
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80
_RRF_K = 60

# Dense retrieval is deliberately permissive so it can gather candidates, but
# a 30-record course corpus must not present every nearest neighbour as a real
# historical match.  The post-filter below requires corroborating lexical
# similarity or a substantially stronger dense score.
_MIN_CORROBORATED_DENSE = 0.55
_MIN_CORROBORATED_SPARSE = 0.10
_MIN_DENSE_ONLY = 0.68
_MIN_SPARSE_ONLY = 0.35


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


def _read_reviewed_records(path: Path = _DATA_PATH) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("review_status") == "reviewed":
                records.append(record)
    return records


@lru_cache(maxsize=1)
def _load_index() -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, float]]]:
    records = _read_reviewed_records()
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


def _rank_sparse(claim: str, *, top_k: int, threshold: float) -> list[tuple[float, dict[str, Any], str]]:
    records, idf, vectors = _load_index()
    query_vector = _tfidf(_char_ngrams(claim), idf)
    ranked: list[tuple[float, dict[str, Any], str]] = []
    for record, vector in zip(records, vectors, strict=True):
        score = _cosine(query_vector, vector)
        candidates = [record["canonical_claim"], *record.get("variants", [])]
        matched_variant = max(candidates, key=lambda value: _cosine(query_vector, _tfidf(_char_ngrams(value), idf)))
        if score >= threshold:
            ranked.append((score, record, matched_variant))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[: max(1, min(top_k, 20))]


def _record_source(record: Mapping[str, Any]) -> tuple[str, str]:
    sources = record.get("authoritative_sources") or []
    if not sources or not isinstance(sources[0], Mapping):
        return "", ""
    source = sources[0]
    url = str(source.get("url", ""))
    publisher = (urlsplit(url).hostname or "").removeprefix("www.")
    return url, publisher


def _sparse_match(score: float, record: Mapping[str, Any], matched_variant: str, *, claim_id: str = "") -> RagMatch:
    url, publisher = _record_source(record)
    return RagMatch(
        record_id=str(record["id"]),
        document_id=str(record["id"]),
        canonical_claim=str(record["canonical_claim"]),
        similarity=round(score, 4),
        sparse_similarity=round(score, 4),
        matched_variant=matched_variant,
        historical_verdict=str(record["verdict"]),
        authoritative_sources=[source["url"] for source in record.get("authoritative_sources", []) if source.get("url")],
        source_url=url,
        publisher=publisher,
        event_date=record.get("event_date"),
        published_at=record.get("event_date"),
        reviewed_at=record.get("reviewed_at"),
        temporal_warning=record.get("temporal_warning"),
        excerpt=str(record.get("explanation", "")),
        claim_ids=[claim_id] if claim_id else [],
        retrieval_sources=["sparse"],
        category=str(record.get("category") or ""),
    )


def retrieve_verified_rumors(
    claim: str,
    *,
    top_k: int = 3,
    threshold: float = _DEFAULT_THRESHOLD,
) -> KnowledgeRetrievalResult:
    """Run the deterministic sparse baseline retained for compatibility."""
    ranked = _rank_sparse(claim, top_k=top_k, threshold=threshold)
    matches = [_sparse_match(score, record, matched_variant) for score, record, matched_variant in ranked]
    return KnowledgeRetrievalResult(
        status="ok" if matches else "no_match",
        query=claim,
        matches=matches,
        threshold=threshold,
        retrieval_mode="sparse",
        document_count=len(_load_index()[0]),
    )


def _record_document(record: Mapping[str, Any]) -> Document:
    source_url, publisher = _record_source(record)
    variants = "；".join(str(value) for value in record.get("variants", []))
    content = "\n".join(
        value
        for value in (
            f"核查主张：{record.get('canonical_claim', '')}",
            f"常见变体：{variants}" if variants else "",
            f"历史核查结论：{record.get('verdict', '')}",
            f"核查说明：{record.get('explanation', '')}",
            f"时效提醒：{record.get('temporal_warning', '')}" if record.get("temporal_warning") else "",
            f"原始来源：{publisher} {source_url}" if source_url else "",
        )
        if value
    )
    return Document(
        page_content=content,
        metadata={
            "record_id": str(record["id"]),
            "document_id": str(record["id"]),
            "canonical_claim": str(record["canonical_claim"]),
            "matched_variant": str(record["canonical_claim"]),
            "historical_verdict": str(record.get("verdict", "")),
            "source_url": source_url,
            "publisher": publisher,
            "published_at": str(record.get("event_date") or ""),
            "reviewed_at": str(record.get("reviewed_at") or ""),
            "temporal_warning": str(record.get("temporal_warning") or ""),
            "category": str(record.get("category") or ""),
            "review_status": "reviewed",
        },
    )


def _load_sidecar(path: Path) -> dict[str, Any] | None:
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        return None
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    return metadata if metadata.get("review_status") == "reviewed" else None


def _load_extra_documents(documents_path: Path = _DOCUMENTS_PATH) -> list[Document]:
    """Load explicitly reviewed Markdown, text, HTML and PDF knowledge files."""
    if not documents_path.exists():
        return []
    documents: list[Document] = []
    for path in sorted(value for value in documents_path.rglob("*") if value.is_file() and not value.name.endswith(".meta.json")):
        metadata = _load_sidecar(path)
        if metadata is None:
            continue
        suffix = path.suffix.lower()
        loaded: list[Document]
        if suffix in {".md", ".txt"}:
            from langchain_community.document_loaders import TextLoader

            loaded = TextLoader(str(path), encoding="utf-8").load()
        elif suffix == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader

            loaded = PyPDFLoader(str(path)).load()
        elif suffix in {".html", ".htm"}:
            from readabilipy import simple_json_from_html_string

            html = path.read_text(encoding="utf-8")
            parsed = simple_json_from_html_string(html, use_readability=True)
            content = str(parsed.get("plain_text") or parsed.get("content") or "")
            loaded = [Document(page_content=content)]
        else:
            continue
        document_id = str(metadata.get("document_id") or path.stem)
        for page_index, document in enumerate(loaded):
            combined = {
                **document.metadata,
                **metadata,
                "document_id": document_id,
                "record_id": str(metadata.get("record_id") or document_id),
                "page_index": page_index,
                "source_path": str(path.relative_to(documents_path)),
            }
            documents.append(Document(page_content=document.page_content, metadata=combined))
    return documents


def validate_rag_documents(documents: list[Document]) -> list[Document]:
    """Reject untraceable records and remove exact duplicate content."""
    validated: list[Document] = []
    seen_hashes: set[str] = set()
    today = datetime.now(UTC).date()
    for document in documents:
        metadata = document.metadata
        document_id = str(metadata.get("document_id", "")).strip()
        source_url = str(metadata.get("source_url", "")).strip()
        publisher = str(metadata.get("publisher", "")).strip()
        reviewed_at = str(metadata.get("reviewed_at", "")).strip()
        if not document_id or not document.page_content.strip():
            raise ValueError("RAG文档缺少document_id或正文")
        if metadata.get("review_status") != "reviewed":
            raise ValueError(f"RAG文档未复核：{document_id}")
        if urlsplit(source_url).scheme not in {"http", "https"} or not urlsplit(source_url).hostname:
            raise ValueError(f"RAG文档缺少公开HTTP(S)来源：{document_id}")
        if not publisher or not reviewed_at:
            raise ValueError(f"RAG文档缺少发布主体或复核日期：{document_id}")
        published_at = str(metadata.get("published_at", "")).strip()
        if published_at:
            try:
                if datetime.fromisoformat(published_at[:10]).date() > today:
                    raise ValueError(f"RAG文档发布日期位于未来：{document_id}")
            except ValueError as exc:
                if "位于未来" in str(exc):
                    raise
                raise ValueError(f"RAG文档发布日期非法：{document_id}") from exc
        content_hash = hashlib.sha256(document.page_content.strip().encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        validated.append(Document(page_content=document.page_content.strip(), metadata={**metadata, "content_hash": content_hash}))
    return validated


def load_rag_documents() -> list[Document]:
    documents = [_record_document(record) for record in _read_reviewed_records()] + _load_extra_documents()
    return validate_rag_documents(documents)


def split_rag_documents(
    documents: list[Document],
    *,
    chunk_size: int = _CHUNK_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
) -> list[Document]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    counts: Counter[str] = Counter()
    totals = Counter(str(chunk.metadata.get("document_id", "")) for chunk in chunks)
    result: list[Document] = []
    for chunk in chunks:
        document_id = str(chunk.metadata.get("document_id", ""))
        index = counts[document_id]
        counts[document_id] += 1
        metadata = {
            **chunk.metadata,
            "chunk_id": f"{document_id}#chunk-{index + 1}",
            "chunk_index": index,
            "chunk_count": totals[document_id],
        }
        result.append(Document(page_content=chunk.page_content.strip(), metadata=metadata))
    return [chunk for chunk in result if chunk.page_content]


def _corpus_hash(documents: list[Document]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: (str(item.metadata.get("document_id", "")), str(item.metadata.get("chunk_id", "")))):
        digest.update(document.page_content.encode("utf-8"))
        digest.update(json.dumps(document.metadata, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _expected_corpus_hash(chunk_size: int, chunk_overlap: int) -> str:
    documents = load_rag_documents()
    return _corpus_hash(
        split_rag_documents(
            documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    )


def _rag_root(persist_dir: str | Path | None = None) -> Path:
    if persist_dir:
        return Path(persist_dir)
    configured = os.getenv("RUMOR_RAG_PERSIST_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(os.getenv("DEER_FLOW_HOME", "runtime")) / "rumorbuster" / "rag"


def _embedding_model_name() -> str:
    return os.getenv("RUMOR_RAG_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL).strip() or _DEFAULT_EMBEDDING_MODEL


def _embedding_device() -> str:
    return os.getenv("RUMOR_RAG_DEVICE", "cpu").strip() or "cpu"


def _vector_enabled() -> bool:
    return os.getenv("RUMOR_RAG_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


@lru_cache(maxsize=2)
def _embedding_model(model_name: str, device: str):
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device, "trust_remote_code": False},
        encode_kwargs={"normalize_embeddings": True, "batch_size": 32},
        multi_process=False,
        show_progress=False,
        cache_folder=os.getenv("HF_HOME") or None,
    )


def build_vector_index(
    *,
    persist_dir: str | Path | None = None,
    model_name: str | None = None,
    device: str | None = None,
    chunk_size: int = _CHUNK_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
    dense_threshold: float = _DEFAULT_DENSE_THRESHOLD,
    sparse_threshold: float = _DEFAULT_SPARSE_THRESHOLD,
    force: bool = False,
) -> dict[str, Any]:
    """Build a versioned Chroma index and atomically publish its pointer."""
    from langchain_chroma import Chroma

    root = _rag_root(persist_dir)
    model = model_name or _embedding_model_name()
    target_device = device or _embedding_device()
    documents = load_rag_documents()
    chunks = split_rag_documents(documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    corpus_sha = _corpus_hash(chunks)
    version_payload = f"{_INDEX_SCHEMA_VERSION}|{model}|{chunk_size}|{chunk_overlap}|{corpus_sha}"
    version = hashlib.sha256(version_payload.encode("utf-8")).hexdigest()[:16]
    indexes = root / "indexes"
    target = indexes / version
    manifest_path = target / "manifest.json"
    if manifest_path.exists() and not force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        indexes.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=indexes))
        try:
            store = Chroma.from_documents(
                documents=chunks,
                embedding=_embedding_model(model, target_device),
                collection_name=_COLLECTION_NAME,
                persist_directory=str(temporary),
                collection_metadata={"hnsw:space": "cosine"},
            )
            del store
            gc.collect()
            manifest = {
                "schema_version": _INDEX_SCHEMA_VERSION,
                "index_version": version,
                "embedding_model": model,
                "distance_metric": "cosine",
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "document_count": len(documents),
                "chunk_count": len(chunks),
                "corpus_sha256": corpus_sha,
                "dense_threshold": max(0.0, min(dense_threshold, 1.0)),
                "sparse_threshold": max(0.0, min(sparse_threshold, 1.0)),
            }
            (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            if target.exists():
                shutil.rmtree(target)
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    root.mkdir(parents=True, exist_ok=True)
    pointer_tmp = root / ".current.json.tmp"
    pointer_tmp.write_text(json.dumps({"index_version": version}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(pointer_tmp, root / "current.json")
    clear_rag_caches()
    return manifest


def _read_current_manifest(root: Path) -> tuple[Path, dict[str, Any]]:
    pointer = root / "current.json"
    if not pointer.exists():
        raise FileNotFoundError("rag_index_missing")
    version = str(json.loads(pointer.read_text(encoding="utf-8")).get("index_version", ""))
    target = root / "indexes" / version
    manifest_path = target / "manifest.json"
    if not version or not manifest_path.exists():
        raise FileNotFoundError("rag_index_missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != _INDEX_SCHEMA_VERSION:
        raise ValueError("rag_index_mismatch")
    if manifest.get("embedding_model") != _embedding_model_name():
        raise ValueError("rag_index_mismatch")
    chunk_size = int(manifest.get("chunk_size", _CHUNK_SIZE))
    chunk_overlap = int(manifest.get("chunk_overlap", _CHUNK_OVERLAP))
    if manifest.get("corpus_sha256") != _expected_corpus_hash(chunk_size, chunk_overlap):
        raise ValueError("rag_index_mismatch")
    return target, manifest


@lru_cache(maxsize=4)
def _load_vector_store_cached(target: str, version: str, model_name: str, device: str):
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=_COLLECTION_NAME,
        persist_directory=target,
        embedding_function=_embedding_model(model_name, device),
    )


def _load_vector_store(root: Path):
    target, manifest = _read_current_manifest(root)
    store = _load_vector_store_cached(str(target), str(manifest["index_version"]), str(manifest["embedding_model"]), _embedding_device())
    return store, manifest


def _dense_candidates(query: str, *, fetch_k: int, threshold: float, root: Path) -> tuple[list[tuple[float, Document]], dict[str, Any]]:
    store, manifest = _load_vector_store(root)
    candidates = store.similarity_search_with_relevance_scores(query, k=fetch_k)
    accepted = [(max(0.0, min(float(score), 1.0)), document) for document, score in candidates if float(score) >= threshold]
    return accepted, manifest


def _dense_match(score: float, document: Document, *, claim_id: str) -> RagMatch:
    metadata = document.metadata
    source_url = str(metadata.get("source_url", ""))
    return RagMatch(
        record_id=str(metadata.get("record_id") or metadata.get("document_id") or metadata.get("chunk_id")),
        document_id=str(metadata.get("document_id", "")),
        chunk_id=str(metadata.get("chunk_id", "")),
        canonical_claim=str(metadata.get("canonical_claim") or metadata.get("title") or document.page_content[:120]),
        similarity=round(score, 4),
        dense_similarity=round(score, 4),
        matched_variant=str(metadata.get("matched_variant") or metadata.get("canonical_claim") or ""),
        historical_verdict=str(metadata.get("historical_verdict", "unknown")),
        authoritative_sources=[source_url] if source_url else [],
        source_url=source_url,
        publisher=str(metadata.get("publisher", "")),
        event_date=str(metadata.get("published_at") or "") or None,
        published_at=str(metadata.get("published_at") or "") or None,
        reviewed_at=str(metadata.get("reviewed_at") or "") or None,
        temporal_warning=str(metadata.get("temporal_warning") or "") or None,
        excerpt=document.page_content[:600],
        claim_ids=[claim_id] if claim_id else [],
        retrieval_sources=["dense"],
        category=str(metadata.get("category") or ""),
    )


def is_high_confidence_rag_match(match: RagMatch) -> bool:
    """Reject nearest-neighbour noise before it reaches reports or timelines."""
    dense = match.dense_similarity or 0.0
    sparse = match.sparse_similarity or 0.0
    if dense >= _MIN_CORROBORATED_DENSE and sparse >= _MIN_CORROBORATED_SPARSE:
        return True
    if dense >= _MIN_DENSE_ONLY:
        return True
    return sparse >= _MIN_SPARSE_ONLY


def _merge_ranked_matches(dense: list[RagMatch], sparse: list[RagMatch], *, top_k: int) -> list[RagMatch]:
    candidates: dict[str, RagMatch] = {}
    fusion: Counter[str] = Counter()
    for source, ranked in (("dense", dense), ("sparse", sparse)):
        for rank, match in enumerate(ranked, start=1):
            key = match.document_id or match.record_id
            fusion[key] += 1 / (_RRF_K + rank)
            existing = candidates.get(key)
            if existing is None:
                candidates[key] = match
                continue
            update: dict[str, Any] = {
                "dense_similarity": existing.dense_similarity if existing.dense_similarity is not None else match.dense_similarity,
                "sparse_similarity": existing.sparse_similarity if existing.sparse_similarity is not None else match.sparse_similarity,
                "retrieval_sources": sorted(set(existing.retrieval_sources + match.retrieval_sources)),
                "claim_ids": sorted(set(existing.claim_ids + match.claim_ids)),
            }
            if not existing.excerpt and match.excerpt:
                update["excerpt"] = match.excerpt
            if not existing.chunk_id and match.chunk_id:
                update["chunk_id"] = match.chunk_id
            candidates[key] = existing.model_copy(update=update)
    ordered = sorted(candidates.items(), key=lambda item: fusion[item[0]], reverse=True)[:top_k]
    return [
        match.model_copy(
            update={
                "fusion_score": round(fusion[key], 6),
                "similarity": round(max(match.dense_similarity or 0.0, match.sparse_similarity or 0.0), 4),
            }
        )
        for key, match in ordered
    ]


def _claim_queries(claim_context: Mapping[str, Any] | str) -> list[tuple[str, str]]:
    if isinstance(claim_context, str):
        return [("claim-1", claim_context.strip())] if claim_context.strip() else []
    queries: list[tuple[str, str]] = []
    for index, item in enumerate(claim_context.get("subclaims") or []):
        if not isinstance(item, Mapping) or not item.get("material", True):
            continue
        text = str(item.get("text", "")).strip()
        if text:
            queries.append((str(item.get("id") or f"claim-{index + 1}"), text))
        if len(queries) >= 3:
            break
    normalized = str(claim_context.get("normalized_claim", "")).strip()
    return queries or ([("claim-1", normalized)] if normalized else [])


def retrieve_rumor_knowledge(
    claim_context: Mapping[str, Any] | str,
    *,
    final_k: int = 6,
    dense_fetch_k: int = 8,
    sparse_fetch_k: int = 8,
    persist_dir: str | Path | None = None,
) -> KnowledgeRetrievalResult:
    """Retrieve reviewed chunks per material subclaim using dense+sparse RRF."""
    queries = _claim_queries(claim_context)
    root = _rag_root(persist_dir)
    manifest: dict[str, Any] = {}
    degradation_codes: list[str] = []
    dense_threshold = _DEFAULT_DENSE_THRESHOLD
    sparse_threshold = _DEFAULT_SPARSE_THRESHOLD
    if _vector_enabled():
        try:
            _, manifest = _read_current_manifest(root)
            dense_threshold = float(manifest.get("dense_threshold", dense_threshold))
            sparse_threshold = float(manifest.get("sparse_threshold", sparse_threshold))
        except FileNotFoundError:
            degradation_codes.append("rag_index_missing")
        except ValueError as exc:
            degradation_codes.append(str(exc))
        except Exception:
            degradation_codes.append("rag_index_corrupt")
    else:
        degradation_codes.append("rag_dense_disabled")

    per_query: list[dict[str, Any]] = []
    combined: dict[str, RagMatch] = {}
    for claim_id, query in queries:
        sparse = [
            _sparse_match(score, record, matched_variant, claim_id=claim_id)
            for score, record, matched_variant in _rank_sparse(query, top_k=sparse_fetch_k, threshold=sparse_threshold)
        ]
        dense: list[RagMatch] = []
        if manifest:
            try:
                dense_ranked, loaded_manifest = _dense_candidates(query, fetch_k=dense_fetch_k, threshold=dense_threshold, root=root)
                manifest = loaded_manifest
                dense = [_dense_match(score, document, claim_id=claim_id) for score, document in dense_ranked]
            except FileNotFoundError:
                degradation_codes.append("rag_index_missing")
            except ValueError as exc:
                degradation_codes.append(str(exc))
            except Exception:
                degradation_codes.append("rag_dense_unavailable")
        fused_candidates = _merge_ranked_matches(dense, sparse, top_k=2)
        fused = [match for match in fused_candidates if is_high_confidence_rag_match(match)]
        if fused_candidates and not fused:
            degradation_codes.append("rag_low_relevance_filtered")
        per_query.append({"claim_id": claim_id, "query": query, "matches": [match.model_dump(mode="json") for match in fused]})
        for match in fused:
            key = match.chunk_id or match.document_id or match.record_id
            existing = combined.get(key)
            if existing is None or (match.fusion_score or 0) > (existing.fusion_score or 0):
                combined[key] = match
            elif claim_id not in existing.claim_ids:
                combined[key] = existing.model_copy(update={"claim_ids": [*existing.claim_ids, claim_id]})

    matches = sorted(combined.values(), key=lambda item: (item.fusion_score or 0.0, item.similarity), reverse=True)[: max(1, min(final_k, 10))]
    degradation_codes = list(dict.fromkeys(degradation_codes))
    dense_available = bool(manifest) and "rag_dense_unavailable" not in degradation_codes
    if matches:
        status = "ok" if dense_available else "partial"
    elif dense_available:
        status = "no_match"
    else:
        status = "partial" if queries else "no_match"
    return KnowledgeRetrievalResult(
        status=status,
        query="；".join(query for _, query in queries),
        matches=matches,
        threshold=sparse_threshold,
        retrieval_mode="hybrid" if dense_available else "sparse_fallback",
        embedding_model=str(manifest.get("embedding_model", _embedding_model_name())),
        index_version=str(manifest.get("index_version", "")),
        document_count=int(manifest.get("document_count", len(_load_index()[0]))),
        chunk_count=int(manifest.get("chunk_count", 0)),
        queries=per_query,
        degradation_codes=degradation_codes,
    )


def format_rag_context(result: KnowledgeRetrievalResult | Mapping[str, Any] | None, *, max_chunks: int = 6, max_chars: int = 3600) -> str:
    """Build bounded, code-owned historical context for the explanation model."""
    if result is None:
        return ""
    if isinstance(result, Mapping) and result.get("status") == "unavailable":
        return ""
    parsed = result if isinstance(result, KnowledgeRetrievalResult) else KnowledgeRetrievalResult.model_validate(result)
    blocks: list[str] = []
    used = 0
    for match in parsed.matches[:max_chunks]:
        excerpt = match.excerpt[:600]
        block = "\n".join(
            value
            for value in (
                f"[KB:{match.chunk_id or match.document_id or match.record_id}]",
                f"历史主张：{match.canonical_claim}",
                f"历史结论：{match.historical_verdict}",
                f"检索片段：{excerpt}" if excerpt else "",
                f"发布主体：{match.publisher}" if match.publisher else "",
                f"发布日期：{match.published_at}" if match.published_at else "",
                f"复核日期：{match.reviewed_at}" if match.reviewed_at else "",
                f"原始来源：{match.source_url}" if match.source_url else "",
                f"时效提醒：{match.temporal_warning}" if match.temporal_warning else "",
            )
            if value
        )
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def clear_rag_caches() -> None:
    _load_index.cache_clear()
    _expected_corpus_hash.cache_clear()
    _load_vector_store_cached.cache_clear()
    _embedding_model.cache_clear()


@tool("retrieve_verified_rumors")
def retrieve_verified_rumors_tool(claim: str, top_k: int = 3, threshold: float = 0.05) -> str:
    """Retrieve local reviewed knowledge; current truth still requires evidence."""
    safe_top_k = max(1, min(int(top_k), 10))
    result = retrieve_rumor_knowledge(claim, final_k=safe_top_k)
    if result.retrieval_mode == "sparse_fallback" and threshold != _DEFAULT_SPARSE_THRESHOLD:
        result = retrieve_verified_rumors(claim, top_k=safe_top_k, threshold=max(0.0, min(float(threshold), 1.0)))
    return result.model_dump_json()


__all__ = [
    "build_vector_index",
    "clear_rag_caches",
    "format_rag_context",
    "is_high_confidence_rag_match",
    "load_rag_documents",
    "retrieve_rumor_knowledge",
    "retrieve_verified_rumors",
    "retrieve_verified_rumors_tool",
    "split_rag_documents",
    "validate_rag_documents",
]
