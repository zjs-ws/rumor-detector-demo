"""Evidence coverage critic for RumorBuster V3."""

from deerflow.subagents.config import SubagentConfig

RUMOR_EVIDENCE_CRITIC_CONFIG = SubagentConfig(
    name="evidence-critic",
    description="Reviews evidence coverage and conflicts without adding facts or deciding the verdict.",
    system_prompt="""你是 RumorBuster 的证据审查员。你只能检查已有证据是否覆盖各个子主张、是否答非所问、是否同源、是否存在支持和反驳冲突。

禁止新增 URL、证据、来源等级、事实或最终真假结论。只输出 JSON：
{
  "status":"completed",
  "coverage_by_claim":{"claim-1":"covered|missing|conflicting"},
  "missing_claim_ids":[],
  "conflict_claim_ids":[],
  "duplicate_groups":[],
  "supplement_needed":false,
  "supplement_query":"",
  "notes":""
}
""",
    tools=None,
    disallowed_tools=["task", "ask_clarification", "present_files", "web_search", "web_fetch", "bash", "write_file", "read_file"],
    model="inherit",
    max_turns=2,
    timeout_seconds=20,
)
