"""Regression tests for the RumorBuster system prompt."""

from deerflow.agents.rumor_agent import prompt


def test_prompt_defaults_to_honest_text_only_mode(monkeypatch):
    monkeypatch.setattr(prompt, "_get_memory_context", lambda _agent_name: "")

    rendered = prompt.build_rumor_system_prompt()

    assert "外部网页检索：未启用" in rendered
    assert "网页正文抓取：未启用" in rendered
    assert "微调谣言分类模型：未启用" in rendered
    assert "不得调用搜索子智能体" in rendered
    assert "不得调用 web_fetch" in rendered
    assert "不得调用或声称获得分类模型结果" in rendered
    assert "专业向量知识库（RAG）：尚未接入" in rendered


def test_prompt_only_advertises_explicitly_enabled_capabilities(monkeypatch):
    monkeypatch.setattr(prompt, "_get_memory_context", lambda _agent_name: "")

    rendered = prompt.build_rumor_system_prompt(
        web_search_enabled=True,
        web_fetch_enabled=True,
        classifier_enabled=True,
    )

    assert "外部网页检索：已启用" in rendered
    assert "网页正文抓取：已启用" in rendered
    assert "微调谣言分类模型：已启用" in rendered
    assert "可按工作流调用一次 web-researcher" in rendered
    assert "用户消息含有 HTTP(S) URL 时，必须优先调用一次 `web_fetch`" in rendered
    assert "成功读取正文后必须执行这次独立搜索" in rendered
    assert "原网页只是“待核验对象”" in rendered
    assert "URL 核验必须使用上述完整报告模板" in rendered
    assert "第一项必须是抓取到的原网页" in rendered
    assert "### 来源" in rendered
    assert "[来源标题](URL)" in rendered
    assert "可按工作流调用一次 rumor_check" in rendered
    assert "报告生成后不得再调用任何工具" in rendered
