from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import checks

CHECK_ID = "00000000-0000-4000-8000-000000000123"


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(checks.router)
    return app


def _fake_client(*, run_result: dict | None = None, state: dict | None = None):
    class FakeClient:
        pass

    client = FakeClient()
    client.assistants = type("Assistants", (), {})()
    client.assistants.search = AsyncMock(
        return_value=[{"assistant_id": "assistant-1"}]
    )
    client.threads = type("Threads", (), {})()
    client.threads.create = AsyncMock(return_value={"thread_id": "check-123"})
    client.threads.get_state = AsyncMock(
        return_value=state
        or {
            "values": {
                "rumor_workflow": {"stage": "report", "trace": []},
                "rumor_report": {
                    "schema_version": "rumorbuster-report-v2",
                    "decision": {"verdict": "证据不足"},
                },
            }
        }
    )
    client.runs = type("Runs", (), {})()
    client.runs.wait = AsyncMock(
        return_value=run_result
        or {
            "rumor_workflow": {"stage": "report", "trace": []},
            "rumor_report": {
                "schema_version": "rumorbuster-report-v2",
                "decision": {"verdict": "非谣言"},
            },
        }
    )
    return client


def test_create_check_runs_existing_rumor_agent(monkeypatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).post(
        "/api/v1/checks",
        json={
            "claim": "某市已经发布新的公共交通规定",
            "source_url": "https://example.com/article",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["check_id"] == "check-123"
    assert body["status"] == "completed"
    assert body["report"]["schema_version"] == "rumorbuster-report-v2"
    client.assistants.search.assert_awaited_once_with(graph_id="rumor_agent")
    client.threads.create.assert_awaited_once()
    _, assistant_id = client.runs.wait.await_args.args
    assert assistant_id == "assistant-1"
    prompt = client.runs.wait.await_args.kwargs["input"]["messages"][0]["content"]
    assert "某市已经发布新的公共交通规定" in prompt
    assert "https://example.com/article" in prompt
    assert client.runs.wait.await_args.kwargs["on_disconnect"] == "continue"


def test_create_check_accepts_claim_without_source_url(monkeypatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).post(
        "/api/v1/checks", json={"claim": "这是一条可以核验的主张"}
    )

    assert response.status_code == 200
    prompt = client.runs.wait.await_args.kwargs["input"]["messages"][0]["content"]
    assert "来源页面" not in prompt


def test_create_check_rejects_short_claim_and_non_public_url(monkeypatch) -> None:
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: _fake_client())
    client = TestClient(_app())

    assert client.post("/api/v1/checks", json={"claim": "短"}).status_code == 422
    response = client.post(
        "/api/v1/checks",
        json={"claim": "这是一个长度足够的待核验主张", "source_url": "http://127.0.0.1/a"},
    )
    assert response.status_code == 422
    response = client.post(
        "/api/v1/checks",
        json={"claim": "这是一个长度足够的待核验主张", "source_url": "http://metadata.internal/a"},
    )
    assert response.status_code == 422


def test_get_check_returns_latest_thread_state(monkeypatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).get(f"/api/v1/checks/{CHECK_ID}")

    assert response.status_code == 200
    assert response.json()["workflow"]["stage"] == "report"
    assert response.json()["report"]["decision"]["verdict"] == "证据不足"
    client.threads.get_state.assert_awaited_once_with(CHECK_ID)


def test_get_check_returns_current_stage_before_report(monkeypatch) -> None:
    client = _fake_client(
        state={
            "values": {
                "rumor_workflow": {"stage": "research", "trace": []},
                "rumor_report": None,
            }
        }
    )
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).get(f"/api/v1/checks/{CHECK_ID}")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["workflow"]["stage"] == "research"
    assert response.json()["report"] is None


def test_get_check_merges_v3_parallel_branch_progress(monkeypatch) -> None:
    client = _fake_client(
        state={
            "values": {
                "rumor_workflow": {"stage": "parallel_collection", "trace": []},
                "rumor_branch_status": {
                    "rag": {"status": "completed", "duration_ms": 4},
                    "web": {"status": "running"},
                },
                "rumor_report": None,
            }
        }
    )
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).get(f"/api/v1/checks/{CHECK_ID}")

    assert response.status_code == 200
    assert response.json()["workflow"]["branch_status"]["rag"]["status"] == "completed"
    assert response.json()["workflow"]["branch_status"]["web"]["status"] == "running"


def test_get_check_returns_404_for_unknown_thread(monkeypatch) -> None:
    client = _fake_client()
    client.threads.get_state = AsyncMock(return_value=None)
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).get(f"/api/v1/checks/{CHECK_ID}")

    assert response.status_code == 404


def test_get_check_returns_404_for_malformed_thread_id(monkeypatch) -> None:
    client = _fake_client()
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).get("/api/v1/checks/not-a-uuid")

    assert response.status_code == 404
    client.threads.get_state.assert_not_awaited()


def test_create_check_returns_503_when_langgraph_is_unavailable(monkeypatch) -> None:
    client = _fake_client()
    client.assistants.search = AsyncMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).post(
        "/api/v1/checks", json={"claim": "这是一条可以核验的主张"}
    )

    assert response.status_code == 503
    assert "LangGraph" in response.json()["detail"]


def test_create_check_timeout_preserves_check_id(monkeypatch) -> None:
    client = _fake_client()

    async def timeout(*args, **kwargs):
        raise TimeoutError

    client.runs.wait = timeout
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).post(
        "/api/v1/checks", json={"claim": "这是一条可以核验的主张"}
    )

    assert response.status_code == 504
    assert response.json()["check_id"] == "check-123"


def test_create_check_asyncio_timeout_preserves_check_id(monkeypatch) -> None:
    client = _fake_client()
    client.runs.wait = AsyncMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr(checks, "get_langgraph_client", lambda: client)

    response = TestClient(_app()).post(
        "/api/v1/checks", json={"claim": "这是一条可以核验的主张"}
    )

    assert response.status_code == 504
    assert response.json()["check_id"] == "check-123"
