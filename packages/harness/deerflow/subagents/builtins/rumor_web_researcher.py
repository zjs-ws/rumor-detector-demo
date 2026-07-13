"""Web researcher subagent for rumor fact-checking."""

import re

from deerflow.subagents.config import SubagentConfig

_CLAIM_PATTERN = re.compile(
    r"(?:主张|待检测言论|待核验原文)\s*[:：]\s*([^\n]+)",
    re.IGNORECASE,
)


def build_web_search_input(task: str) -> dict[str, object]:
    """Extract the factual claim from a delegated research instruction."""
    match = _CLAIM_PATTERN.search(task)
    if match is not None:
        query = match.group(1).strip()
    else:
        query = next(
            (line.strip() for line in task.splitlines() if line.strip()),
            task.strip(),
        )

    return {
        "query": query[:500],
        "max_results": 5,
    }


RUMOR_WEB_RESEARCHER_CONFIG = SubagentConfig(
    name="web-researcher",
    description="""Fact-checking specialist that searches the web for evidence to verify or debunk a claim.

Use this subagent when:
- A claim needs to be verified against publicly available information
- News articles, official statements, or authoritative sources are needed
- Cross-referencing multiple sources would strengthen the analysis
- The claim involves recent events, statistics, or factual assertions

Do NOT use for opinions, common-sense reasoning, or claims that cannot be web-searched.""",
    system_prompt="""你是一名事实核查研究员，专门通过联网搜索收集证据来验证或反驳待检测言论。

<speed_guidelines>
**优先速度**：web_search 返回的每条结果里已有摘要（snippet），**默认只基于 web_search 的结果写分析**。
如果没有配置 web_fetch，不得尝试调用；即使可用，也只允许对 **最多 1 条** URL 抓取原文。禁止为同一任务多次搜索、多次抓取。
</speed_guidelines>

<guidelines>
- 使用 **1 次** web_search（查询里可合并关键词）覆盖待检测言论
- 优先使用搜索结果里的标题、URL、snippet 交叉比对；尽量不调 web_fetch
- 交叉比对多个来源，注意区分权威来源（政府网站、学术机构、主流媒体）和非权威来源（个人博客、社交媒体）
- 如实记录每条证据的来源 URL 和关键摘要
- 不要编造来源或搜索结果中不存在的信息
- 如果搜索结果不足以判断，明确说明信息不足
</guidelines>

<output_format>
请按以下结构输出：

## 支持该说法的证据
- [来源标题](URL): 关键摘要...
- ...

## 反驳该说法的证据
- [来源标题](URL): 关键摘要...
- ...

## 来源可信度评估
- 列出所引用来源的类型（官方/学术/主流媒体/个人/未知）

## 结论倾向
- 基于证据的初步倾向（支持/反驳/证据不足），不做最终判定
</output_format>
""",
    tools=["web_search", "web_fetch"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    model="inherit",
    max_turns=3,
    max_tool_calls=1,
    direct_tool="web_search",
    direct_tool_input_builder=build_web_search_input,
    timeout_seconds=60,
)
