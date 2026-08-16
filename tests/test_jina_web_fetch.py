"""Tests for structured and traceable webpage fetching."""

import json
from datetime import datetime

import requests

from deerflow.community.jina_ai import tools


def test_decode_web_content_repairs_mislabeled_chinese_encodings():
    utf8 = "当心洁厕灵误用".encode()
    gb18030 = "洁厕灵有消毒作用吗".encode("gb18030")

    assert tools._decode_web_content(utf8, "latin-1") == "当心洁厕灵误用"
    assert tools._decode_web_content(gb18030, "latin-1") == "洁厕灵有消毒作用吗"


def test_web_fetch_returns_structured_source_metadata(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    monkeypatch.setattr(
        tools,
        "get_app_config",
        lambda: type(
            "Config",
            (),
            {
                "get_tool_config": lambda _self, _name: type(
                    "ToolConfig",
                    (),
                    {"model_extra": {"timeout": 12, "max_chars": 80}},
                )()
            },
        )(),
    )
    monkeypatch.setattr(
        tools.JinaClient,
        "crawl",
        lambda _self, _url, return_format, timeout: (
            "Title: 示例报道\nPublished Time: 2024-05-06\n\nMarkdown Content:\n\n这是网页正文。"
        ),
    )

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/news"})
    payload = json.loads(result)

    assert payload["source_url"] == "https://example.com/news"
    assert payload["requested_url"] == "https://example.com/news"
    assert payload["title"] == "示例报道"
    assert payload["content"] == "Title: 示例报道\nPublished Time: 2024-05-06\n\nMarkdown Content:\n\n这是网页正文。"
    assert payload["published_at"] == "2024-05-06"
    assert payload["truncated"] is False
    assert payload["content_chars"] == len(payload["content"])
    assert datetime.fromisoformat(payload["fetched_at"]).tzinfo is not None


def test_web_fetch_blocks_non_public_urls(monkeypatch):
    crawl_called = False

    def _crawl(*_args, **_kwargs):
        nonlocal crawl_called
        crawl_called = True
        return "should not run"

    monkeypatch.setattr(tools.JinaClient, "crawl", _crawl)

    result = tools.web_fetch_tool.invoke({"url": "http://127.0.0.1/private"})

    assert result.startswith("Error:")
    assert "public HTTP(S)" in result
    assert crawl_called is False


def test_web_fetch_uses_bounded_local_fallback_without_jina_key(monkeypatch):
    class FakeResponse:
        is_redirect = False
        is_permanent_redirect = False
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "ISO-8859-1"

        @property
        def apparent_encoding(self):
            raise AssertionError("流式响应消费后不得再读取 apparent_encoding")

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size == 64 * 1024
            yield "<html><title>本地抓取</title><p>正文内容</p></html>".encode()

        def close(self):
            return None

    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.setattr(tools.JinaClient, "crawl", lambda _self, _url, return_format, timeout: "Error: unavailable in test")
    monkeypatch.setattr(
        tools.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (tools.socket.AF_INET, tools.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(tools.requests, "get", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(
        tools.readability_extractor,
        "extract_article",
        lambda _html: type(
            "Article",
            (),
            {"to_markdown": lambda _self: "# 本地抓取\n\n正文内容"},
        )(),
    )
    monkeypatch.setattr(
        tools,
        "get_app_config",
        lambda: type(
            "Config",
            (),
            {"get_tool_config": lambda _self, _name: None},
        )(),
    )

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/article"})
    payload = json.loads(result)

    assert payload["source_url"] == "https://example.com/article"
    assert payload["requested_url"] == "https://example.com/article"
    assert payload["title"] == "本地抓取"
    assert payload["content"] == "# 本地抓取\n\n正文内容"


def _fake_local_response(status=200, redirect_to=None):
    class FakeResponse:
        is_redirect = redirect_to is not None
        is_permanent_redirect = False
        status_code = status
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}")
            return None

        def iter_content(self, chunk_size):
            yield "<html><title>重试页</title><p>正文</p></html>".encode()

        def close(self):
            return None

    if redirect_to is not None:
        FakeResponse.headers = {**FakeResponse.headers, "location": redirect_to}
    return FakeResponse()


def _stub_local_fetch_env(monkeypatch):
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.setattr(tools.JinaClient, "crawl", lambda _self, _url, return_format, timeout: "Error: unavailable in test")
    monkeypatch.setattr(
        tools.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (tools.socket.AF_INET, tools.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(
        tools,
        "get_app_config",
        lambda: type("Config", (), {"get_tool_config": lambda _self, _name: None})(),
    )
    monkeypatch.setattr(
        tools.readability_extractor,
        "extract_article",
        lambda _html: type("Article", (), {"to_markdown": lambda _self: "正文"})(),
    )


def test_web_fetch_skips_jina_without_key(monkeypatch):
    crawl_called = {"count": 0}

    def _crawl(*_args, **_kwargs):
        crawl_called["count"] += 1
        return "should not run"

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.JinaClient, "crawl", _crawl)
    monkeypatch.setattr(tools.requests, "get", lambda *_args, **_kwargs: _fake_local_response())

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/article"})
    payload = json.loads(result)

    assert crawl_called["count"] == 0
    assert payload["content"] == "正文"


def test_local_fallback_extracts_pdf_text(monkeypatch):
    class FakePdfResponse:
        is_redirect = False
        is_permanent_redirect = False
        status_code = 200
        headers = {"content-type": "application/pdf"}
        encoding = None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"%PDF-1.7 fake pdf bytes"

        def close(self):
            return None

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", lambda *_args, **_kwargs: FakePdfResponse())
    monkeypatch.setattr(tools, "_extract_pdf_text", lambda _raw: "PDF正文：吸烟有害健康。")

    result = tools.web_fetch_tool.invoke({"url": "https://apps.who.int/example.pdf"})
    payload = json.loads(result)

    assert payload["source_url"] == "https://apps.who.int/example.pdf"
    assert payload["content"] == "PDF正文：吸烟有害健康。"
    assert payload["truncated"] is False


def test_local_fallback_reports_error_for_empty_pdf_text(monkeypatch):
    class FakePdfResponse:
        is_redirect = False
        is_permanent_redirect = False
        status_code = 200
        headers = {"content-type": "application/pdf"}
        encoding = None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"%PDF-1.7 fake pdf bytes"

        def close(self):
            return None

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", lambda *_args, **_kwargs: FakePdfResponse())
    monkeypatch.setattr(tools, "_extract_pdf_text", lambda _raw: "")

    result = tools.web_fetch_tool.invoke({"url": "https://apps.who.int/example.pdf"})

    assert result.startswith("Error:")
    assert "PDF" in result


def test_local_fallback_retries_transient_5xx_then_succeeds(monkeypatch):
    attempts = {"count": 0}

    def _get(*_args, **_kwargs):
        attempts["count"] += 1
        return _fake_local_response(status=503 if attempts["count"] == 1 else 200)

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(tools.requests, "get", _get)

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/article"})
    payload = json.loads(result)

    assert attempts["count"] == 2
    assert payload["content"] == "正文"


def test_local_fallback_does_not_retry_403(monkeypatch):
    attempts = {"count": 0}

    def _get(*_args, **_kwargs):
        attempts["count"] += 1
        return _fake_local_response(status=403)

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(tools.requests, "get", _get)

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/article"})

    assert attempts["count"] == 1
    assert result.startswith("Error:")


def test_local_fallback_uses_browser_headers(monkeypatch):
    captured = {}

    def _get(*_args, **_kwargs):
        captured["kwargs"] = _kwargs
        return _fake_local_response()

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", _get)

    tools.web_fetch_tool.invoke({"url": "https://example.com/article"})

    headers = captured["kwargs"]["headers"]
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert "Accept" in headers
    assert "Accept-Language" in headers


def test_local_fallback_empty_article_returns_error(monkeypatch):
    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", lambda *_args, **_kwargs: _fake_local_response())
    monkeypatch.setattr(
        tools.readability_extractor,
        "extract_article",
        lambda _html: type("Article", (), {"to_markdown": lambda _self: ""})(),
    )

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/article"})

    assert result.startswith("Error:")
    assert "no readable text" in result


def test_local_fallback_allows_five_redirects(monkeypatch):
    attempts = {"count": 0}

    def _get(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 5:
            return _fake_local_response(redirect_to="https://example.com/hop")
        return _fake_local_response()

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", _get)

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/start"})
    payload = json.loads(result)

    assert attempts["count"] == 6
    assert payload["content"] == "正文"


def test_local_fallback_rejects_six_redirects(monkeypatch):
    attempts = {"count": 0}

    def _get(*_args, **_kwargs):
        attempts["count"] += 1
        return _fake_local_response(redirect_to="https://example.com/hop")

    _stub_local_fetch_env(monkeypatch)
    monkeypatch.setattr(tools.requests, "get", _get)

    result = tools.web_fetch_tool.invoke({"url": "https://example.com/start"})

    assert attempts["count"] == 6
    assert "redirect limit" in result
