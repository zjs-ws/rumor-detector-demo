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
必须且只允许调用 **1 次** web_search。若 web_fetch 可用，从搜索结果中选择最多 **4 条** 最能形成直接证据或传播节点的 URL 抓取正文。不得重试或扩展搜索。
</speed_guidelines>

<guidelines>
- 使用 **1 次** web_search（查询里可合并关键词）覆盖待检测言论
- 搜索摘要只可作为候选线索，必须标记 `directness=snippet_only`，不能凑证据门槛
- 对最多四条高价值候选调用 web_fetch；正文成功返回后才可标记为直接证据
- 交叉比对多个来源，注意区分权威来源（政府网站、学术机构、主流媒体）和非权威来源（个人博客、社交媒体）
- 如实记录每条证据的来源 URL 和关键摘要
- 同一新闻稿的转载必须使用相同的 independent_group，不得伪装成独立来源
- 不要编造来源或搜索结果中不存在的信息
- 如果搜索结果不足以判断，明确说明信息不足
- 只负责证据采集与字段初标，不输出最终真假结论
</guidelines>

<output_format>
只输出一个 JSON 对象，不要使用 Markdown 代码围栏：
{
  "status":"ok|insufficient|unavailable",
  "evidence":[{
    "id":"web-1", "title":"...", "url":"https://...", "publisher":"...",
    "published_at":"YYYY-MM-DD或null", "stance":"support|refute|context",
    "source_level":"A|B|C|D", "directness":"direct|indirect|snippet_only",
    "authority_scope":true, "authority_reason":"为何具有该事项职权",
    "independent_group":"机构或原始稿件组", "claim_ids":["claim-1"],
    "temporal_relevance":"current|event_match|historical_match|timeless|stale|unknown",
    "current_validity_confirmed":false, "fetched_at":"ISO-8601时间或null",
    "extraction_status":"ok|snippet_only|failed", "summary":"...", "provenance":"web",
    "claim_variant":"该页面传播或核验的主张版本", "change_summary":"相对上一版本的变化或空字符串"
  }],
  "notes":"..."
}
</output_format>
""",
    tools=["web_search", "web_fetch"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    model="inherit",
    max_turns=7,
    max_tool_calls=5,
    tool_call_limits={"web_search": 1, "web_fetch": 4},
    timeout_seconds=55,
)
