"""Tests for structured and traceable webpage fetching."""

import json
from datetime import datetime

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
