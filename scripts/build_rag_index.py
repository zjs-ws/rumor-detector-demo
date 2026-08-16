"""Validate the reviewed corpus and build RumorBuster's local Chroma index."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from deerflow.agents.rumor_agent.rag import build_vector_index, load_rag_documents, split_rag_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persist-dir", type=Path, default=None)
    parser.add_argument("--model", default=os.getenv("RUMOR_RAG_EMBEDDING_MODEL", "GanymedeNil/text2vec-large-chinese"))
    parser.add_argument("--device", default=os.getenv("RUMOR_RAG_DEVICE", "cpu"))
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=80)
    parser.add_argument("--dense-threshold", type=float, default=0.35)
    parser.add_argument("--sparse-threshold", type=float, default=0.05)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_size <= 0 or args.chunk_overlap < 0 or args.chunk_overlap >= args.chunk_size:
        raise SystemExit("chunk参数非法：要求 chunk_size > chunk_overlap >= 0")
    documents = load_rag_documents()
    chunks = split_rag_documents(documents, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    summary = {
        "status": "validated" if args.validate_only else "building",
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "embedding_model": args.model,
        "device": args.device,
    }
    if args.validate_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    manifest = build_vector_index(
        persist_dir=args.persist_dir,
        model_name=args.model,
        device=args.device,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        dense_threshold=args.dense_threshold,
        sparse_threshold=args.sparse_threshold,
        force=args.force,
    )
    print(json.dumps({"status": "ready", **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
