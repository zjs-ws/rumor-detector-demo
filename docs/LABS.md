# RumorBuster 答辩实验手册

V2 阶段门控实验见 [WORKFLOW_V2_IMPLEMENTATION.md](WORKFLOW_V2_IMPLEMENTATION.md)，V3 显式图、并行汇合与回退实验见 [WORKFLOW_V3_IMPLEMENTATION.md](WORKFLOW_V3_IMPLEMENTATION.md)。

所有实验保存四类证据：执行命令、控制台日志、结果截图、结论说明。建议放入 `docs/evidence/<日期>-<实验名>/`，不要提交真实 API Key。

## 实验 1：完整消息与状态变化

1. 启动服务并新建核验任务。
2. 浏览器开发者工具查看流式请求；后端日志按 `thread_id` 过滤。
3. 依次记录 HumanMessage、带 `tool_calls` 的 AIMessage、ToolMessage、最终 AIMessage。
4. 在线程状态接口确认最终出现 `rumor_report`。
5. 用同一 `thread_id` 再问一次，再换新 `thread_id`，对比历史消息。

验收：能指出工具调用参数来自 AIMessage，工具返回为何必须带 `tool_call_id`，以及 Checkpointer 保存的是图状态而不是“模型脑内记忆”。

## 实验 2：能力开关与降级

分别执行：

- 移除搜索配置：不应出现 `task`，RAG 仍运行，最终可降级证据不足；
- 移除抓取配置：用户 URL 不应被声称已读取；
- 移除 `RUMOR_MODEL_BASE_URL`：不装配 `rumor_check`；
- 模拟分类器超时：返回 `status=unavailable,label=uncertain`，证据规则不变。

保存 Agent 启动日志中的模型名与 capability flags，以及实际工具列表。

## 实验 3：工具手调

在项目环境中运行相关单元测试：

```bash
uv run pytest tests/test_rumor_model_tool.py tests/test_rumor_rag.py tests/test_rumor_evidence_decision.py -v
```

验收：能解释严格 JSON、`Unknown` 不再被 `no` 子串误判、混合 RAG Top-K、以及 A/B 门槛。

## 实验 4：V3 并行与子 Agent 预算

开启调试日志并执行一个需要搜索的主张。日志中确认：

- `rag`、`web`、`classifier` 与专业场景的 `authority` 开始和结束区间存在重叠；
- 普通研究员只有 `web_search` 和 `web_fetch` 权限，搜索最多 1 次、抓取最多 4 次；
- 权威研究员搜索最多 1 次、抓取最多 2 次；critic 没有工具；
- 任一分支失败时其他分支正常完成，最终仍进入规则裁决；
- 子 Agent 返回严格 JSON 和实际 ToolMessage；最终 verdict 只来自 fan-in 后的规则节点。

可直接运行脚本化测试：

```bash
uv run pytest tests/test_rumor_graph_v3.py -v
```

验收：能从 `branch_status.started_at/finished_at` 证明并行，而不是仅凭流程图声称并行。

## 实验 5：Sandbox 安全

在 Rumor Agent 暂时暴露 `write_file`/`read_file` 工具的实验配置中，使用独立测试线程：

1. 调用前查询线程状态，`sandbox` 为空；
2. 写 `/mnt/user-data/outputs/demo.md`；
3. 调用后状态包含 `sandbox_id`，并在该线程 outputs 目录找到文件；
4. 尝试读 `/mnt/user-data/../other-thread/secret.txt`；
5. 尝试写 `/etc/rumorbuster-demo`；
6. 两次操作都必须被拒绝，日志和返回值不得泄露真实宿主机路径。

注意：LocalSandbox 使用宿主进程，隔离强度主要来自路径校验；容器 Sandbox 才能提供更强执行隔离。本实验不要在生产机器执行任意未知命令。

## 实验 6：规则与中间件不可覆盖

构造一条 A 级反驳证据，同时让微调模型返回 `non_rumor`，并让最终模型草稿写“非谣言”。最终应出现：

- `assess_evidence.verdict=谣言`；
- `classifier_consistency=conflict`；
- 最终 Markdown 被校正为“谣言”；
- 前端证据卡显示“与证据冲突”；
- `rumor_report.decision.verdict=谣言`。

再构造 A 对 A，结果必须是“存疑”；两条同稿转载 B 不能满足独立来源门槛。

## 实验 7：离线评测与消融

```bash
PYTHONPATH=packages/harness uv run python scripts/evaluate_rumorbuster.py
```

输出位于 `evaluation/results/latest.json` 和 `.md`。报告至少比较完整规则、仅分类器、去时效校验、去独立性校验；另报告可核验分流准确率和 RAG Recall@3。

`evaluation/v3_comprehensive_cases.json` 固定了 V3 课程评测的 40 条组成。它引用上述可重复组件样本；答辩时必须说明它不是 40 次实时网页搜索。真实网页另保存输入、工具原始结果、trace、结构化报告、截图、日期和备用结果。

## 90 秒介绍

我们没有把大模型当作最终裁判。LangGraph 提供状态图、并行汇合和检查点，DeerFlow 提供模型、工具和受限子 Agent 执行基础；RumorBuster 在其上实现显式事实核验 StateGraph。输入经过原网页读取、主张拆分和可核验性后，并行运行本地 HuggingFace/Chroma 与 TF-IDF 混合 RAG、普通网页研究、可选微调分类器，以及专业场景的权威研究。分支失败可以独立降级。汇合后，代码校验 URL、来源职权、时效和独立性，无工具的 critic 只能指出缺口，最多申请一次补检。最终由固定 A/B 门槛和子主张规则裁决；大模型只负责提取与解释，终局节点删除未观察链接并重新绑定规则结论。前端展示分支耗时、证据、冲突、排除原因和传播时间线。V2 串行门控图仍保留作为回退和架构演进对照。
