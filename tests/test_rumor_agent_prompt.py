"""Regression tests for the RumorBuster system prompt."""

from deerflow.agents.rumor_agent import prompt


def test_prompt_defaults_to_honest_text_only_mode(monkeypatch):
    monkeypatch.setattr(prompt, "_get_memory_context", lambda _agent_name: "")

    rendered = prompt.build_rumor_system_prompt()

    assert "外部网页检索：未启用" in rendered
    assert "微调谣言分类模型：未启用" in rendered
    assert "不得调用搜索子智能体" in rendered
    assert "不得调用或声称获得分类模型结果" in rendered
    assert "专业向量知识库（RAG）：尚未接入" in rendered


def test_prompt_only_advertises_explicitly_enabled_capabilities(monkeypatch):
    monkeypatch.setattr(prompt, "_get_memory_context", lambda _agent_name: "")

    rendered = prompt.build_rumor_system_prompt(
        web_search_enabled=True,
        classifier_enabled=True,
    )

    assert "外部网页检索：已启用" in rendered
    assert "微调谣言分类模型：已启用" in rendered
    assert "可按工作流调用一次 web-researcher" in rendered
    assert "可按工作流调用一次 rumor_check" in rendered
    assert "报告生成后不得再调用任何工具" in rendered
