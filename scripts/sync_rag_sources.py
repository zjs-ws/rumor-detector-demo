"""Fetch an exact allowlisted URL manifest into an unreviewed RAG staging file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from deerflow.community.jina_ai.tools import web_fetch_tool

_ALLOWED_DOMAINS = {
    "piyao.org.cn",
    "gov.cn",
    "nhc.gov.cn",
    "samr.gov.cn",
    "cma.gov.cn",
    "mem.gov.cn",
    "pbc.gov.cn",
    "csrc.gov.cn",
    "who.int",
    "fda.gov",
    "cdc.gov",
    "nasa.gov",
    "ipcc.ch",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("DEER_FLOW_HOME", "runtime")) / "rumorbuster/rag/staging/synced.jsonl",
    )
    return parser.parse_args()


def _allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in _ALLOWED_DOMAINS)


def main() -> int:
    args = parse_args()
    entries = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    staged: list[dict[str, object]] = []
    for entry in entries:
        url = str(entry.get("source_url", ""))
        if not _allowed(url):
            staged.append({**entry, "review_status": "rejected", "sync_error": "source_domain_not_allowlisted"})
            continue
        raw = web_fetch_tool.invoke({"url": url})
        if str(raw).startswith("Error:"):
            staged.append({**entry, "review_status": "staging", "sync_error": str(raw)})
            continue
        try:
            fetched = json.loads(str(raw))
        except json.JSONDecodeError:
            staged.append({**entry, "review_status": "staging", "sync_error": "invalid_fetch_result"})
            continue
        staged.append(
            {
                **entry,
                "title": entry.get("title") or fetched.get("title"),
                "body": fetched.get("content", ""),
                "resolved_url": fetched.get("source_url", url),
                "fetched_at": fetched.get("fetched_at"),
                "review_status": "staging",
                "content_hash": hashlib.sha256(str(fetched.get("content", "")).encode("utf-8")).hexdigest(),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in staged) + "\n", encoding="utf-8")
    print(json.dumps({"status": "staged", "count": len(staged), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
