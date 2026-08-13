#!/usr/bin/env python3
"""Check the public Nginx entry point without invoking an external model."""

from __future__ import annotations

import argparse
import json
import urllib.request


def read_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - operator supplied URL
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    ready = read_json(f"{base_url}/healthz")
    if ready.get("status") != "ready" or ready.get("langgraph") != "ready":
        raise RuntimeError(f"unexpected readiness response: {ready}")

    openapi = read_json(f"{base_url}/api/openapi.json")
    required = {"/api/v1/checks", "/api/v1/checks/{check_id}"}
    missing = required.difference(openapi.get("paths", {}))
    if missing:
        raise RuntimeError(f"missing public API paths: {sorted(missing)}")

    print(json.dumps({"status": "ready", "base_url": base_url}, ensure_ascii=False))


if __name__ == "__main__":
    main()
