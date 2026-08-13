# Claude Code 项目交接

更新日期：2026-07-23

## 当前目标

将 RumorBuster 完善为课程作业和可持续扩展的个人作品集项目：

```text
文字 / URL / 浏览器划词
→ 提取可核验主张
→ 抓取原网页
→ 搜索独立公开证据
→ 接收微调模型辅助信号
→ 生成证据卡片与公开传播时间线
→ 输出带可追溯引用的结构化报告
```

完整时间表、两人分工、课程材料和验收指标见
`docs/COURSE_PROJECT_PLAN.md`。

## 当前工程状态

- 开发分支：`feature/import-mcp-frontend`
- 后端：LangGraph + FastAPI Gateway，Docker Compose 本地运行
- 前端：Next.js 16 / React 19，已产品化为 RumorBuster
- 已有输入：文本、网页 URL、Chrome 划词入口
- 已有证据能力：
  - 安全抓取一个用户提供的公开 HTTP(S) 页面；
  - DuckDuckGo 独立公开来源检索；
  - 运行时引用白名单与证据不足降级；
  - Markdown 报告导出。
- 当前主模型：DeepSeek API
- 计划接入的辅助模型：
  `congyang/fine-tuned-qwen-2.5-3b-instruct-based-on-rumor-datasets`

## 当前未完成里程碑

按顺序完成：

1. 微调模型适配器
   - 环境变量：`RUMOR_MODEL_BASE_URL`、`RUMOR_MODEL_API_KEY`、
     `RUMOR_MODEL_NAME`
   - OpenAI 兼容接口、`temperature=0`
   - 严格 JSON 协议：`rumor | non_rumor | uncertain`
   - 修复 `Unknown` 被子串 `no` 错判的问题
   - 删除固定虚假置信度
   - 超时、错误标签和无效 JSON 安全降级
2. 主张类型与可核验性分流
3. 统一结构化核验结果 Schema
4. 证据卡片和公开传播时间线生成
5. 前端结构化报告、证据卡片和时间线 UI
6. 30–50 条独立评测、部署文档、许可与课程材料

`tests/test_rumor_model_tool.py` 是微调模型适配器的先行测试；继续开发时
先审查该文件，再让测试真实失败并实现生产代码。

## 必须保持的产品约束

- 微调模型只是辅助风险信号，最终结论由公开证据链决定。
- 没有独立证据时，只能输出存疑、证据不足或暂不可核验。
- 未来随机事件、私人事实、主观意见和非事实表达必须单独分流。
- 每条可点击引用必须来自本轮实际抓取或搜索结果。
- “本轮最早公开记录”不得描述为绝对谣言源头。
- URL 抓取失败、搜索失败和模型不可用时不得虚构结果。
- `.env`、`config.yaml`、`.claude/deepseek.env`、`runtime/`、模型权重和
  原始数据集不得进入 Git。

## Claude Code 与 DeepSeek

使用：

```bash
./scripts/claude-deepseek.sh
```

脚本通过 `https://api.deepseek.com/anthropic` 启动 Claude Code，默认主
模型为 `deepseek-v4-pro[1m]`，轻量/子任务模型为
`deepseek-v4-flash`。真实 Key 从进程环境、忽略的
`.claude/deepseek.env` 或忽略的根目录 `.env` 获取。

2026-07-23 的最小连通性测试已经到达官方端点，但账户返回
`HTTP 402 Insufficient Balance`。充值后重新运行启动脚本即可；不要因
这个错误改回 Anthropic 官方地址，也不要把 Key 写入共享设置。

进入 Claude Code 后运行：

```text
/continue-rumorbuster
```

提交前运行：

```text
/validate-rumorbuster
```
