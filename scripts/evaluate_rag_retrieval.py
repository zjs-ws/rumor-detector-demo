"""Evaluate sparse or hybrid local RAG against the checked-in RAG cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deerflow.agents.rumor_agent.rag import retrieve_rumor_knowledge, retrieve_verified_rumors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evaluation/rag_cases.jsonl"))
    parser.add_argument("--mode", choices=("sparse", "hybrid"), default="hybrid")
    parser.add_argument("--persist-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    hits_at_1 = 0
    hits_at_3 = 0
    reciprocal_rank = 0.0
    false_matches = 0
    rows: list[dict[str, object]] = []
    for case in cases:
        if args.mode == "sparse":
            result = retrieve_verified_rumors(case["claim"], top_k=3, threshold=0.05)
        else:
            result = retrieve_rumor_knowledge(case["claim"], final_k=3, persist_dir=args.persist_dir)
        ids = [match.record_id for match in result.matches]
        expected = case.get("expected_record_id")
        rank = ids.index(expected) + 1 if expected in ids else None
        if expected:
            hits_at_1 += int(rank == 1)
            hits_at_3 += int(rank is not None and rank <= 3)
            reciprocal_rank += 1 / rank if rank else 0
        elif ids:
            false_matches += 1
        rows.append({"id": case.get("id"), "expected": expected, "retrieved": ids, "rank": rank, "status": result.status})
    positives = sum(1 for case in cases if case.get("expected_record_id")) or 1
    negatives = sum(1 for case in cases if not case.get("expected_record_id")) or 1
    output = {
        "mode": args.mode,
        "case_count": len(cases),
        "positive_count": positives,
        "negative_count": negatives if any(not case.get("expected_record_id") for case in cases) else 0,
        "recall_at_1": round(hits_at_1 / positives, 4),
        "recall_at_3": round(hits_at_3 / positives, 4),
        "mrr": round(reciprocal_rank / positives, 4),
        "negative_rejection_rate": round(1 - false_matches / negatives, 4) if any(not case.get("expected_record_id") for case in cases) else None,
        "rows": rows,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
