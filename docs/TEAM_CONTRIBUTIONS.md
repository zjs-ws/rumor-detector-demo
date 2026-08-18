# 团队贡献与成员分工（DeerFlow 框架改造记录）

> 本文档服务于课程报告"成员分工与贡献"、PPT"成员工作描述"、答辩开场分工介绍和
> 05-小组工作日志。归属依据为 git 提交记录（`git shortlog -sne --all`）与各模块
> 实际改动文件；贡献比例按课程要求"依据实际工作日志、Issue、Commit 和产物填写，
> 不提前写死"。

## 一、对 DeerFlow 框架的改造清单

RumorBuster 基于 DeerFlow 开源框架（上游作者 Cong Yang 等，本仓库 fork 自
deer-flow）做领域化二次开发。**上游提供**的通用能力：Agent 运行时与工具系统、
子 Agent 调度、Sandbox、模型工厂、通用中间件、Memory、MCP 与 Skills。团队在
此基础上新增/改造了以下模块：

### 1. 谣言核验智能体（`packages/harness/deerflow/agents/rumor_agent/`）

- V3 显式 LangGraph `StateGraph`（`graph_v3.py`）：可核验性分流 → `Send`
  并行 fan-out（本地 RAG / 普通网页研究 / 可选 LoRA 分类 / 专业权威研究 /
  默认关闭的时间线研究）→ reducer 汇合 → 确定性裁决；模型解释失败也能
  生成完整报告
- 确定性证据管线（`evidence.py`、`source_policy.py`）：一条职权匹配 A /
  两条独立 B 的裁决门槛、来源分级、独立性/直接性/时效性校验
- 汇合后确定性补抓（`rescue`）与候选扫描（`sweep`）：代码自己抓取网页、
  按主张关键词逐字选取引文，不依赖模型自觉
- 确定性时态修正（`research_plan.py`）：无时态标记的普遍性事实归为
  general，不适用 365 天时效淘汰
- 职权注册表（`data/source_registry.json`，22 条官方来源）：WHO/CDC/NHC、
  NIH、NASA、FDA、Smithsonian、NIST、CIA/NSA 解密记录、Apple/Google/Mozilla
  产品文档等，生成受控权威域名查询
- 本地向量 + TF-IDF 混合 RAG（`rag.py`、`scripts/build_rag_index.py`），
  历史知识不参与当前证据门槛
- 传播时间线（`timeline.py`、`timeline_research.py`）：代码执行搜索与抓取，
  不运行模型循环，条目锁定 `timeline_only` 不参与裁决

### 2. RumorBuster 专属中间件（`agents/middlewares/`）

- `rumor_workflow_middleware.py`：研究结果严格 JSON 解析（围栏/散文容错、
  期望键门控）、模型乱填字段（fetch_attempts/timeline_event_type/
  temporal_relevance）确定性归一化
- `rumor_evidence_policy_middleware.py`：V2 终局引用白名单与证据不足强制降级

### 3. 子智能体（`subagents/`）

- `builtins/rumor_web_researcher.py`、`rumor_authority_researcher.py`：
  受限研究员（web_search=1，web_fetch≤3/2，55 秒预算），输出严格 JSON
  证据协议
- `executor.py` 领域化改造：工具调用预算包装器（每工具限额拒绝并继续，
  防止模型耗尽轮次）、子智能体工具执行故障诊断与稳定化

### 4. 社区工具领域化（`community/`）

- Tavily 工具：结构化抓取协议（source_url/fetched_at/正文哈希），与 V3
  溯源绑定契约一致
- Jina/本地抓取加固：浏览器 UA、瞬时错误有限重试、5 跳重定向、空正文报错、
  PDF 正文提取（pypdf）
- DuckDuckGo 无 key 搜索作为备选信息源

### 5. 统一核验 API 与部署（`app/gateway/`、根目录编排）

- `POST/GET /api/v1/checks` 统一核验接口（未来 MCP 只需薄封装）
- 制品下载 MIME 强制映射（HTML/XHTML/SVG 一律附件，防 XSS）
- Docker Compose 单入口生产编排（Nginx 8080）、`quickstart.sh` 一键启动
  （含双 key 校验）、Tavily 默认信息源的快速上手文档

### 6. 前端核验工作区（`frontend/`）

- 证据实验室界面：结构化证据卡片、A/B/C/D 分级展示、排除原因、证据时间线、
  Markdown/JSON 导出与打印
- `rumor-report-view.ts`/`rumor-report-card.tsx`：报告 schema 兼容 v1/v2/v3，
  分支状态、来源等级校正、子主张裁决展示
- 消息处理稳定性：ToolMessage 按 `tool_call_id` 归组（并发分支乱序）、
  空值防护、CommandPalette 动态加载

### 7. 浏览器划词扩展（`browser-extension/`）

- Chrome Manifest V3 扩展：划词右键核验、URL fragment 隐私传递、
  可配置服务地址、预填不自动提交

### 8. 评测体系与数据（`evaluation/`、`模型微调/bench mark/`）

- 40 条固定组成离线评测清单（可核验性/RAG/证据规则/混合子主张/URL 路由）
- 30 条真实联网验收脚本与失败基线、URL 冒烟、三案例 V2/V3 留痕
- 模型微调 6 项基准评测：早期预警准确率、依据溯源率、解释质量与自洽度、
  对抗扰动抵抗度、极低误报率、端到端决策延迟

## 二、两人工作归属矩阵

| 模块 | 成员一 zjswz111 | 成员二 baitea | git 依据 |
|---|---|---|---|
| rumor_agent V3 证据链（graph/evidence/source_policy/research_plan/registry） | ✅ 主体 | | 19 提交中 rumor_agent 相关 12+ 次 |
| 确定性补抓 rescue / 候选扫描 sweep / general 时态 | ✅ | | 48de287、0b3365f、d58f460 |
| rumor 中间件（工作流门控、证据政策） | ✅ 主体 | ✅ fetch_attempts 归一化（387a7a3） | 两人共改 rumor_workflow_middleware.py |
| 子智能体（研究员、工具预算包装器） | ✅ 主体 | ✅ 工具执行故障诊断与稳定化（1888b71） | executor.py 两人共改，baitea 3 提交中 2 个在此 |
| 信息源工具（Tavily/Jina/DDG、PDF、抓取加固） | ✅ | | 48de287、240b83f |
| 统一核验 API / Gateway | ✅ | | app/gateway 5 文件 |
| 前端核验工作区主体（268 文件） | ✅ | ✅ 消息归组/报告卡片/usage 防护/layout 稳定性（387a7a3、26dc364） | frontend utils.ts +106 行为 baitea |
| 浏览器扩展 | ✅ | | browser-extension 8 文件 |
| evaluation 体系 + 微调 6 项基准 | ✅ | | evaluation 32 文件、bench mark 33 文件 |
| 部署编排与文档 | ✅ | ✅ Dockerfile.local 构建稳定性（26dc364） | |
| 需求分析、演示案例、报告校对、模拟答辩、视频录制 | ✅ 共同 | ✅ 共同 | 课程模板规定 |

**贡献比例（待填写）**：按课程要求依据实际工作日志/Issue/Commit 填写。
当前 git 客观参考：提交数 19:3，改动文件 451:8（上游 7 个基线提交不计）。

## 三、供材料直接引用

**课程报告第一页（成员工作和贡献比）**：

> 成员一 zjswz111：负责智能体与后端，完成谣言核验 V3 显式状态图与确定性
> 证据规则、受控权威来源注册表、Tavily 信息源接入与确定性补抓/候选扫描、
> 统一核验 API、评测体系与微调模型六项基准、浏览器划词扩展及部署编排。
> 成员二 baitea：负责子智能体执行稳定化与证据-前端衔接，诊断并修复子智能体
> 工具执行故障，完成证据字段归一化、前端消息乱序归组、报告卡片防护与本地
> 构建稳定性改进。两人共同完成需求分析、演示案例、报告校对与模拟答辩。
> （贡献比例依据工作日志与 Commit 记录填写）

**PPT 第二页（成员工作描述）**：

> A（zjswz111）· 智能体与后端：V3 证据链与确定性裁决、职权注册表、
> Tavily 结构化抓取、补抓/扫描、评测与基准、扩展与部署
> B（baitea）· 稳定化与前端衔接：子智能体执行修复、证据 JSON 容错、
> 消息归组与报告卡片、构建稳定性

**答辩 1 分钟分工**：

> 项目两人协作：我（A）负责智能体与后端——V3 状态图、证据规则、权威来源
> 注册表、信息源改造和评测体系；搭档（B）负责子智能体执行稳定化与前端
> 证据展示衔接，并共同完成演示案例、报告和模拟答辩。具体分工与 git 留痕
> 见小组工作日志。

## 附：上游基线说明

本仓库 fork 自 DeerFlow 开源项目（上游作者 Cong Yang 等 7 个提交，2026-03
至 04），提供 Agent 运行时、工具系统、Sandbox、模型工厂等通用基础设施；
团队所有领域化改造均在上游基线上进行，三层架构与归属矩阵详见
`docs/ARCHITECTURE_OWNERSHIP.md`。
