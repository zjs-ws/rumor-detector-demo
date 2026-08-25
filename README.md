# FactTrace（证迹）

可追溯证据驱动的事实核验工作台，支持网页端与浏览器划词入口。

**FactTrace** 强调从主张到网页、原文引文、来源等级和规则结论的完整证据轨迹。为兼容既有 API、LangGraph 图 ID、配置项和课程归档材料，代码中的 `RumorBuster` 标识暂时保留；它们均指向本项目。

课程项目已于 2026-08-25 结项，当前归档版本位于
`feature/import-mcp-frontend`。课程开发与评测记录见
[课程项目计划](docs/COURSE_PROJECT_PLAN.md)，架构归属和实现边界见
[工程交接文档](docs/CLAUDE_HANDOFF.md)。仓库继续保留复现实验与二次开发所需的
源码、配置模板、测试、评测清单和答辩文档。

用户可以在网页端粘贴新闻、社交媒体消息或其他文本进行核验，也可以通过浏览器扩展选中文字并直接进入核验工作区。当前分支已提供 FactTrace 网页端、浏览器划词入口、智能体后端、API Gateway、模型调用与本地持久化能力。

| 证据实验室首页                                                         | 结构化历史实测报告                                                              |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| ![RumorBuster 亮色首页](docs/screenshots/frontend/home-light-1280.png) | ![RumorBuster 暗色结构化报告](docs/screenshots/frontend/showcase-dark-1440.png) |

## 课程结项状态

结项基线汇总（2026-08-25）：

- 2026-08-17 留档的 RumorBuster 定向回归测试共 127 项通过；
- 2026-08-22 重跑共 178 项通过，另有 2 项旧测试仍按 DuckDuckGo 和 4 次抓取的历史约束断言，未同步到当前 Tavily 与最多 3 次抓取配置；
- Ruff、ESLint、TypeScript 和 Next.js 生产构建通过；
- `compose.prod.yaml` 配置校验通过；
- 训练集和原测试集保持冻结，部署前后的 SHA-256 一致；
- Qwen2.5-3B LoRA 微调权重已完成 1940 条三分类离线测试，总体准确率 90.00%，该指标不代表整套联网核验系统准确率；
- 本地假 HTTP 服务已验证 V3 确实调用 ModelScope `/v1/chat`，且分类标签不能覆盖规则结论。

已验证：

- Docker Compose 本地部署
- RumorBuster Next.js 网页端
- DeepSeek 模型调用
- 谣言检测智能体基础对话
- API Gateway 健康检查
- 面向脚本与未来 MCP 的统一核验 API：`POST/GET /api/v1/checks`
- Nginx 单入口、生产前端镜像与持久化目录的单机云部署配置
- HTML、XHTML 与 SVG 等可执行网页产物强制下载，且 MIME 判断不依赖宿主机差异
- SQLite 会话与检查点持久化
- 无需额外密钥、保留原始搜索结果的 DuckDuckGo 公开网页检索
- 输入公开网页 URL 后抓取正文，并在报告中生成可点击、可追溯的来源引用
- URL-only 输入会先读取原网页再提取主张；结构化提取不兼容时回退到严格 JSON，仍无法提取则要求补充主张，不搜索“网页主要内容”等操作指令
- 运行时校验最终引用：移除本轮工具未返回的链接；未引用独立外部来源时，自动降级为“存疑（证据不足）/低证据强度”
- 可核验性预分流，避免对观点、隐私和未来随机事件伪造真假结论
- 30 条已复核种子记录，以及符合课程链路的 Document 加载、中文分块、HuggingFace Embedding、Chroma 持久化和 TF-IDF 混合检索；历史知识仍不参与当前证据门槛
- 结构化证据、A/B/C/D 来源分级、独立性/直接性/时效性校验与确定性裁决
- 受控官方来源职权表包含 WHO、政府/监管机构及气候领域 NASA/IPCC；官方域名仍必须与当前主张职权匹配才可升为 A 级
- V3 显式 LangGraph `StateGraph`：通过 `Send` 并行运行本地 RAG、普通网页研究、可选分类器、专业权威研究和默认关闭的确定性时间线研究，以 reducer 汇合后再审查与裁决
- V2 串行阶段门控图以 `rumor_agent_v2` 保留，可用于回归比较和故障回退
- ModelScope `/v1/chat` 与 OpenAI Chat 双协议微调模型适配；最多三个子主张顺序分类，精确映射 `Yes/No/Unknown`，记录脱敏审计信息，标签仅作辅助信号
- 六类可追溯文本风险线索、核验目标与搜索提示；风险线索不会进入证据门槛
- 子主张级 LoRA 标签、规则结论和一致性对照，非法标签不会默认映射为“非谣言”
- `rumorbuster-report-v3`、并行分支状态、来源等级校正、子主张裁决和安全降级报告，并兼容读取 v1/v2
- 受限 `evidence-critic` 检查子主张覆盖与确定性裁决门槛，不能新增证据、URL、等级或 verdict；覆盖但门槛不足时也可申请唯一一次补检
- `web_fetch` 在结构化工具结果中记录抓取时间，V3 只按成功抓取的 URL 由代码回填 `fetched_at`；搜索摘要或模型自报时间不能冒充正文抓取
- 历史事件、当前状态与未来表达由代码按确定性优先级校正；无时态标记的普遍性事实由代码确定为“普遍性事实”（general），不适用 365 天时效淘汰，模型对无标记主张的 current_status 判定会被代码降级；“药物、治疗、疫苗”等领域词只影响专业路由，不再误触发当前状态时效规则
- 汇合后对最多 2 条“已观察到但未成功抓取/摘引未验证”的 A/B 级直接证据做确定性补抓：代码自己抓取正文、按主张关键词选取逐字引文，通过校验后正常参与裁决；补抓失败保持排除，不降低裁决门槛
- CIA/MKULTRA、塔斯基吉研究、NASA 与 NSA/斯诺登监控项目等已登记实体生成受控权威域名查询；模型可以建议查询词，但不能指定或提升官方来源
- 直接网页证据必须同时具有成功抓取状态、正文哈希和可在抓取内容中反查的连续原文引文，否则不能进入“一条 A / 两条独立 B”的裁决门槛
- 按本轮实际证据的发布日期生成“证据发布时间序列”，用于比较材料新旧，不宣称识别首发、转载关系或传播路径
- 确定性时间线研究分支（`RUMOR_TIMELINE_ENABLED=true` 开启）：代码执行 1 次搜索加最多 5 个并发抓取，不运行模型循环；条目被代码锁定 `timeline_only=true`，不能参与裁决门槛；至少 3 条不同日期的已抓取记录才显示就绪时间线，否则与不足裁决并列展示并明确标注“时间线证据不足”
- 30 条真实联网验收评估脚本与 2026-08-14 失败基线（`evaluate_real_factchecks.py`），统计明确判定率、已判准确率、虚构 URL、正文引文与规则绑定
- 结构化证据卡片、排除原因、Markdown/JSON 下载和打印
- Chrome 浏览器划词核验入口
- “证据实验室”亮暗双主题界面：首屏突出规则结论、证据强度与可追溯来源，技术审计默认折叠
- V3 七阶段执行进度和 RAG、普通网页、权威来源、LoRA 四类常开并行能力状态；开启时间线研究后追加“传播脉络研究”分支状态
- 三个带真实运行日期的历史实测案例；存档结果与实时核验明确区分并复用同一报告组件
- 浏览器扩展可在设置页修改 RumorBuster 地址，默认使用生产编排入口 `http://localhost:8080`
- 正式 Markdown/JSON 导出不包含模型 reasoning、工具参数、系统提示词、密钥或服务地址
- Apple Silicon Docker 环境

截至 2026-08-16 的增量验证：

- 谣言智能体相关 72 项测试在 Docker 一次性容器中通过（含新增的时间线研究与向量 RAG 测试）；
- 前端 TypeScript typecheck、`compose.yaml` 与 `compose.prod.yaml` 配置校验通过。

截至 2026-08-17 的增量验证：

- 信息源切换 Tavily（免费 key 即可用），并新增汇合后确定性补抓：对最多 2 条"已观察到但未成功抓取/摘引未验证"的 A/B 级直接证据，由代码抓取正文并按主张关键词选取逐字引文，通过校验后正常参与裁决，失败保持排除；
- "抽烟有害身体健康"连续两轮真实运行均判"非谣言（high）"，分别由国家卫健委《中国吸烟危害健康报告2020》与 WHO 烟草实况报道的 A 级证据支撑；
- 定向回归 127 项通过，40 条离线清单全部指标 1.0，无回归。
- 职权注册表新增 NSA/斯诺登监控项目实体（dni.gov/odni.gov/nsa.gov/icontherecord.tumblr.com），恢复研究子智能体的每工具限额强制（防止模型耗尽轮次不产出 JSON），模型乱填的 timeline_event_type 不再导致整条证据被拒。

截至 2026-08-24 的模型评测补充：

- Qwen2.5-3B LoRA 微调权重完成 1940 条 `Yes/No/Unknown` 三分类离线测试，总体准确率 90.00%，Macro F1 为 0.89，Weighted F1 为 0.90；
- `No`、`Unknown`、`Yes` 的 F1 分别为 0.88、0.84、0.95，其中 `Unknown` 召回率 0.78，是当前相对薄弱类别；
- 该结果只代表微调模型的离线文本分类能力，不代表 RumorBuster 整套联网核验系统准确率。详细口径见 `docs/FINETUNED_3B_EVALUATION.md`。

结项边界与可选后续工作：

- 微调模型服务接入后的 9 条双跑冒烟、三个真实网页案例双跑和大规模联网验证没有作为结项指标完成；
- 注册登录、生产鉴权、MCP 和更大规模知识库属于产品化后续范围；
- 当前版本为课程归档与开发预览，不建议直接暴露到公网。

## 仓库与大文件说明

GitHub 仓库只保存可审阅、可复现的源码和小型课程产物，不分发本地密钥、运行数据库、依赖目录、构建缓存、课程参考 PDF 或完整模型权重。

以下目录仅存在于开发机器，不应提交：

| 路径 | 内容 | 恢复方式 |
|---|---|---|
| `final_result/` | Qwen2.5-3B 微调模型权重与 tokenizer | 从独立模型存储下载，或按训练流程重新导出 |
| `runtime/` | Hugging Face 缓存、Chroma 索引和运行数据 | 重新下载模型并运行 RAG 索引构建命令 |
| `.venv/` | Python 虚拟环境 | `uv sync` 或项目安装命令 |
| `frontend/node_modules/` | 前端依赖 | 在 `frontend/` 执行 `pnpm install --frozen-lockfile` |
| `frontend/.next/` | Next.js 构建缓存与产物 | 执行前端构建命令重新生成 |
| `rag/` | 本地课程参考资料 | 从课程资料备份恢复 |

其中 `final_result/` 含数 GB 权重，普通 GitHub 仓库无法承载；释放本地空间前必须先确认模型已存入专用模型仓库或其他备份位置。仓库中的 `.env.example`、`.env.production.example` 和 `config.example.yaml` 只含配置模板，真实密钥始终保留在被忽略的本地配置中。

## 快速启动（小白 5 步上手）

### 第 0 步：准备三样东西（约 5 分钟）

| 需要什么 | 去哪弄 | 说明 |
|---|---|---|
| **Docker Desktop** | https://www.docker.com/products/docker-desktop | 安装后打开并等待引擎启动 |
| **DeepSeek API Key**（付费） | https://platform.deepseek.com → 充值 → API Keys → 创建 | 大模型调用按量计费，一次核验约几分钱 |
| **Tavily API Key**（免费） | https://tavily.com → 用 Google/GitHub 登录 → Dashboard 里复制 `tvly-` 开头的 key | 网页搜索与正文抓取，免费额度 1000 credits/月，一次核验约消耗 3~5 |

两个 key 都只需要复制粘贴，不要发给别人、不要提交到 Git。

### 第 1 步：克隆项目

```bash
git clone \
  --branch feature/import-mcp-frontend \
  --recurse-submodules \
  https://github.com/zjs-ws/rumor-detector-demo.git

cd rumor-detector-demo
```

已经克隆过的队友：

```bash
git fetch origin
git switch feature/import-mcp-frontend
git pull --ff-only
git submodule update --init --recursive
```

`模型微调/数据集` 是冻结的独立数据仓库，以 Git 子模块方式引用，不要在主项目中重新生成、移动或提交它。

### 第 2 步：创建本地配置（复制两个模板）

```bash
cp -n .env.example .env
cp -n config.example.yaml config.yaml
```

### 第 3 步：把两个 key 填进 `.env`

打开 `.env` 文件，把占位符替换成你自己的 key（别的行不用动）：

```bash
DEEPSEEK_API_KEY=sk-你的DeepSeek密钥
TAVILY_API_KEY=tvly-你的Tavily密钥
```

默认信息源是 **Tavily**（搜索和抓取都在 Tavily 服务器完成，能渲染 JS、解析
PDF、不受本机 IP 反爬影响）。没有 Tavily key 时，也可以按 `config.example.yaml`
里的注释把两处 `use:` 换成 DuckDuckGo + 本地抓取的无 key 备选方案（稳定性较差）。

### 第 4 步：一键启动

```bash
./scripts/quickstart.sh
```

脚本会自动检查 Docker、校验两个 key、复制配置、构建并启动全部服务，最后
打印访问地址。首次构建需要下载镜像，耐心等几分钟。

首次使用本地向量知识库前，单独构建 Chroma 索引（可选，不构建也能用）：

```bash
docker compose -f compose.prod.yaml --profile maintenance run --rm rag-indexer
```

### 第 5 步：打开网页，试一条核验

浏览器打开 **http://localhost:8080/workspace/chats/new**，输入：

> 抽烟有害身体健康

预期 30~60 秒后出报告：**判定结论"非谣言（高置信度）"**，证据列表里能看到
国家卫健委或 WHO 的 A 级证据标注"用于裁决"，主张时态显示"普遍性事实"。

服务健康检查（返回 `status: ready` 即正常）：

```bash
curl http://localhost:8080/healthz
```

### 常见问题（新手排错）

| 现象 | 原因与处理 |
|---|---|
| `quickstart.sh` 提示 TAVILY_API_KEY 未配置 | 按第 0 步去 tavily.com 注册，把 key 填进 `.env` 重跑脚本 |
| 报告显示"证据不足" | 最常见是网络抖动导致抓取失败——**再核验一次**；连续多轮仍不足才说明该主张确实缺证据或来源确实不可达 |
| 启动后页面打不开 | `docker compose -f compose.prod.yaml ps` 看容器是否 healthy；`docker compose -f compose.prod.yaml logs -f` 看报错 |
| 端口 8080 被占用 | 在 `.env` 里加 `RUMORBUSTER_HTTP_PORT=其他端口` 后重启 |
| 想跑回归测试确认环境完好 | 见下方"队友接手顺序"的测试命令（127 项定向回归） |

### 定向回归测试

```bash
docker compose -f compose.prod.yaml run --rm -T \
  -v "$PWD/packages:/app/packages:ro" \
  -v "$PWD/tests:/app/tests:ro" \
  -v "$PWD/scripts:/app/scripts:ro" \
  -v "$PWD/evaluation:/app/evaluation:ro" \
  langgraph uv run pytest \
    tests/test_rumor_*.py \
    tests/test_tavily_web_fetch.py \
    tests/test_jina_web_fetch.py \
    tests/test_subagent_executor.py \
    tests/test_finetuned_classifier_evaluation.py \
    tests/test_checks_api.py \
    tests/test_demo_runner.py -q
```

## 队友接手顺序

1. 先阅读 [V3 工作流说明](docs/WORKFLOW_V3_IMPLEMENTATION.md)和[三层架构归属](docs/ARCHITECTURE_OWNERSHIP.md)。
2. 运行上面的 113 项定向回归，确认环境没有破坏当前基线。
3. 不修改训练集、原测试集和既有 Benchmark，不重新训练模型。
4. 有 GPU 资源后，按[微调模型部署手册](docs/MODELSCOPE_CLASSIFIER_DEPLOYMENT.md)建立 SSH 隧道并运行真实验收。
5. 只把阻断测试、真机结果和脱敏演示产物提交到当前协作分支；不要提交密钥、运行数据库或模型权重。

本仓库没有分发三篇本地 Word 论文原文，它们已被 `模型微调/*.docx` 规则忽略。仓库只保留不含论文全文的[论文经验落地矩阵](docs/PAPER_TO_IMPLEMENTATION.md)。

## 使用 DeepSeek 驱动 Claude Code

本项目提供 `scripts/claude-deepseek.sh`，通过 DeepSeek 的 Anthropic
兼容端点启动 Claude Code。脚本默认复用根目录 `.env` 中已有的
`DEEPSEEK_API_KEY`，不会将密钥写入受 Git 跟踪的配置文件。

```bash
cd ~/Projects/rumor-detector-demo
./scripts/claude-deepseek.sh
```

进入会话后执行 `/continue-rumorbuster`，Claude Code 会读取当前课程计划、
工程交接和未完成里程碑继续开发；提交前可执行
`/validate-rumorbuster`。

默认模型分工：

- 主会话、复杂编码：`deepseek-v4-pro[1m]`
- 子任务和轻量调用：`deepseek-v4-flash`
- 推理强度：`max`

如需单独配置 Claude Code 的 Key 或覆盖模型：

```bash
cp .claude/deepseek.env.example .claude/deepseek.env
nano .claude/deepseek.env
./scripts/claude-deepseek.sh
```

`.claude/deepseek.env` 已被 Git 忽略。不要把真实 Key 写入
`.claude/settings.json`、README 或提交记录。该启动方式按 DeepSeek API
用量计费，不会消耗 Claude Pro/Max 订阅额度。

## 安装浏览器划词扩展

1. 启动生产编排，确认 `http://localhost:8080` 可以访问。
2. 在 Chrome 打开 `chrome://extensions`。
3. 开启“开发者模式”，点击“加载已解压的扩展程序”。
4. 选择仓库中的 `browser-extension/` 目录。
5. 在任意网页选中文字，右键选择“用 RumorBuster 核验”。

如果入口不是本机 `8080`，在扩展详情页打开“扩展程序选项”，填写新的
HTTP(S) 基础地址。地址保存在 `chrome.storage.sync`，更换服务器时无需重新打包。

扩展会打开新对话并预填原文与来源页面，不会自动发送。选中文字通过 URL
fragment 传递，不会进入本地服务的 HTTP 请求或访问日志；前端读取后会立即
清除地址栏中的 fragment。

## 服务地址

- 生产统一入口：`http://localhost:8080`
- 历史实测案例：`http://localhost:8080/workspace/showcase`
- 聚合健康检查：`http://localhost:8080/healthz`
- 统一核验 API：`http://localhost:8080/api/v1/checks`
- LangGraph 流式协议：`http://localhost:8080/api/langgraph/*`

开发编排可按 Compose 配置直接访问前端、Gateway 与 LangGraph 端口；最终用户和
浏览器扩展应使用 Nginx 的 `8080` 单入口。

`2024` 端口仅用于后端开发调试，不应直接暴露给最终用户。

## 生产模式与统一 API

生产模式只发布 Nginx 端口，网页、Gateway 和 LangGraph 通过 Docker 内网互访：

```bash
cp .env.production.example .env.production
docker compose -f compose.prod.yaml config
docker compose -f compose.prod.yaml up -d --build
python3 scripts/check_production_ready.py
```

网页与 LangGraph 流式接口使用同源相对地址，不把本机服务地址编译进生产包。第三方程序调用 `POST /api/v1/checks` 创建核验，再用 `GET /api/v1/checks/{check_id}` 查询；未来 MCP 只需薄封装这两个接口。完整的启动、备份、恢复与故障处理见 [生产部署手册](docs/PRODUCTION_DEPLOYMENT.md)。

## 常用命令

- 查看状态：`docker compose ps`
- 查看日志：`docker compose logs -f`
- 重新构建：`docker compose up -d --build --force-recreate`
- 停止服务：`docker compose down`
- 环境检查：`./scripts/doctor.sh`
- DeepSeek 模式启动 Claude Code：`./scripts/claude-deepseek.sh`
- URL 核验端到端冒烟测试：`docker compose run --rm -T -v "$PWD/scripts:/app/scripts:ro" -e LANGGRAPH_BASE_URL=http://langgraph:2024 langgraph uv run python scripts/smoke_url_factcheck.py`
- 固定三案例 V2/V3 留痕：`docker compose -f compose.prod.yaml run --rm -T -v "$PWD/evaluation:/app/evaluation" langgraph uv run python scripts/run_demo_cases.py --base-url http://langgraph:2024`
- 真实模型 9 条双跑冒烟：`python3 scripts/run_classifier_smoke.py --base-url http://127.0.0.1:18000 --repeats 2`
- 冻结早期预警集评测：`python3 scripts/evaluate_finetuned_classifier.py --base-url http://127.0.0.1:18000 --dataset early`
- 冻结对抗集评测：`python3 scripts/evaluate_finetuned_classifier.py --base-url http://127.0.0.1:18000 --dataset adversarial`
- 校验本地RAG语料：`docker compose -f compose.prod.yaml run --rm -T langgraph uv run python scripts/build_rag_index.py --validate-only`
- 构建本地Chroma索引：`docker compose -f compose.prod.yaml --profile maintenance run --rm rag-indexer`
- 对比RAG召回：`docker compose -f compose.prod.yaml run --rm -T langgraph uv run python scripts/evaluate_rag_retrieval.py --mode hybrid`
- 前端纯函数测试：`corepack pnpm --dir frontend test`
- 浏览器扩展测试：`node --test browser-extension/tests/*.mjs`
- 前端质量检查：`corepack pnpm --dir frontend format && corepack pnpm --dir frontend lint && corepack pnpm --dir frontend typecheck && corepack pnpm --dir frontend build`

## 配置安全

可以提交：

- `.env.example`
- `config.example.yaml`
- `compose.yaml`
- `Dockerfile.local`

禁止提交：

- `.env`
- `.env.production`
- `config.yaml`
- `.claude/deepseek.env`
- `runtime/`
- `local-backups/`
- `模型微调/*.docx`
- 模型权重

每位开发者使用自己的 API Key。真实密钥只保存在本地 `.env` 中。

## 项目结构

- `app/`：API Gateway 与消息通道
- `packages/harness/`：智能体运行核心
- `packages/harness/deerflow/agents/rumor_agent/`：谣言检测智能体
- `evaluation/`：可核验性、RAG、证据规则，以及按 V3 计划固定组成的 40 条综合离线评测清单
- `模型微调/数据集/`：冻结训练集和原测试集子模块；首次克隆必须使用 `--recurse-submodules`
- `模型微调/bench mark/`：既有课程 Benchmark，当前仅运行、不重新生成
- `frontend/`：RumorBuster Next.js 网页端
- `browser-extension/`：Chrome Manifest V3 划词核验扩展
- `compose.yaml`：本地 Docker 编排
- `compose.prod.yaml`：Nginx 单入口的生产编排
- `Dockerfile.local`：本地开发镜像
- `scripts/quickstart.sh`：一键启动
- `scripts/doctor.sh`：环境与安全检查
- `scripts/evaluate_rumorbuster.py`：确定性回归、对比与消融评测
- `scripts/build_rag_index.py`：校验复核语料，使用HuggingFace Embedding构建版本化Chroma索引
- `scripts/evaluate_rag_retrieval.py`：输出TF-IDF或混合RAG的Recall@1/3、MRR和负例拒绝率
- `scripts/sync_rag_sources.py`：按精确允许清单把 URL 抓取到未复核 RAG staging，等待人工复核
- `scripts/evaluate_finetuned_classifier.py`：通过真实 `/v1/chat` 运行冻结的早期预警集与对抗集，不生成 Mock 指标
- `scripts/run_classifier_smoke.py`：在 GPU 隧道建立后运行 9 条、每条两次的真实模型冒烟验收
- `scripts/run_demo_cases.py`：独立线程运行固定案例，保存 V2/V3 报告、trace、分支耗时、抓取溯源和校验摘要
- `scripts/evaluate_real_factchecks.py`：运行30条独立线程的真实联网验收，分别统计明确判定率、已判准确率、虚构 URL、正文引文和规则绑定；其结果不能由 Mock 代替
- `docs/ARCHITECTURE_OWNERSHIP.md`：LangGraph/DeerFlow/RumorBuster 归属矩阵
- `docs/DEFENSE_STUDY_GUIDE.md`：源码学习与答辩卡
- `docs/LABS.md`：日志、Sandbox、线程状态和消融实验手册
- `docs/WORKFLOW_V2_IMPLEMENTATION.md`：阶段门控、来源规则、时间线和答辩实验留痕
- `docs/WORKFLOW_V3_IMPLEMENTATION.md`：显式 StateGraph、并行汇合、受限子 Agent、回退策略与学习留痕
- `docs/RAG_IMPLEMENTATION.md`：课程标准向量 RAG 的 Loader、切片、Embedding、Chroma、混合召回、降级与答辩边界
- `docs/REAL_FACTCHECK_ACCEPTANCE.md`：2026-08-14 真实测试暴露问题的修复链路与 30 条联网验收标准
- `docs/PRODUCTION_DEPLOYMENT.md`：云主机部署、统一 API、备份恢复与故障处理
- `docs/MODELSCOPE_CLASSIFIER_DEPLOYMENT.md`：短租 GPU、SSH 隧道、真实模型调用与验收
- `docs/SOCIAL_CONTEXT_FUTURE.md`：未启用的评论质证扩展边界和 Fixture
- `docs/PAPER_TO_IMPLEMENTATION.md`：三篇论文思想、已实现内容和未实现边界

## 已知限制

1. 默认只配置 DeepSeek 主模型。
2. 微调分类模型服务不打包进 RumorBuster Compose；需在 GPU 主机独立启动并通过 SSH 隧道接入。没有真实 GPU 日志前不得把适配测试写成模型评测结果。
3. 每个可核验主张最多运行一次普通发现检索（最多3次正文抓取）和一次受控权威检索（最多2次正文抓取）；没有匹配到注册机构时，权威分支不会自由选择域名。当前取消第三次模型自由补检。搜索摘要只作线索，不能凑正式证据门槛。时间线研究分支默认关闭（`RUMOR_TIMELINE_ENABLED=false`）；开启后代码执行 1 次搜索与最多 5 个并发抓取，条目锁定 `timeline_only=true` 不参与裁决，至少 3 条不同日期的已抓取记录才显示就绪时间线。没有平台转发关系或可靠新闻档案数据时，不宣称具备传播溯源能力。
4. 智能体已加入模型/工具调用上限，后续仍需补齐真实证据源后的复杂流程测试。
5. 当前智能体服务使用本地开发模式和无鉴权配置。
6. 注册登录尚未接入；浏览器扩展当前为本地加载版，默认连接 `http://localhost:8080`，可在扩展设置中更换为未来的云端地址。
7. 每轮最多抓取用户提供的 1 个公开 HTTP(S) URL，正文最多保留 12,000 个字符。搜索与抓取默认走 Tavily（能渲染常见 JS 页面并解析 PDF），登录墙、付费墙或明确阻止爬取的网页仍可能无法读取；私网、localhost 与非 HTTP(S) 地址会被拒绝。无 key 备选方案（DuckDuckGo + 本地抓取）对反爬站点的成功率明显更低。
8. 本地 RAG 已具备课件要求的 Loader、中文 Chunk、HuggingFace Embedding、Chroma Retriever 与 Prompt 上下文注入；当前正式语料仍以30条人工复核种子记录为主，未构建索引时自动退回TF-IDF。无论哪种模式，命中历史知识都不会直接决定当前主张。
9. Sandbox 中间件已装配，但不是事实裁决核心；LocalSandbox 不是容器级安全边界，公网环境应使用更强隔离 Provider。
10. 评论质证只保留接口草案，当前没有评论爬取、评论分析或传播树能力。
11. 2026-08-14 的真实测试曾暴露历史主张误判时态、权威查询不定向和无正文引文等问题；相关代码已进入修复分支，但只有 `evaluation/real_e2e_cases.json` 的30条真实联网验收达到门槛后，才对外使用“稳定谣言核验系统”的表述。
12. 确定性补抓每轮最多补抓 2 条 A/B 级直接证据，只对"已出现在本轮搜索结果中"的 URL 生效；补抓失败或引文无法与主张匹配时保持排除，不降低裁决门槛。

## 产品方向

独立网页端和浏览器划词扩展共用同一套新对话流程。浏览器入口只负责安全地预填待核验内容，实际提交仍由用户确认。V3 由显式节点和条件边控制顺序，在可核验性判断后并行取证；所有分支先经 Schema、来源、时效、独立性与 URL 校正，再由确定性规则裁决。子 Agent 不投票，通用大模型只负责结构化提取和解释，终局节点重新绑定规则结论与观察到的 URL。前端优先展示 `rumorbuster-report-v3`，同时保留旧报告与 Markdown 兼容输出。

## 开源基础与团队工作

RumorBuster 采用 LangGraph 作为状态与 Agent 运行基础，并基于 DeerFlow 开源框架进行领域化二次开发。框架提供状态图、工具、子 Agent、中间件、Sandbox 和配置基础；团队实现事实核验工作流、本地向量与关键词混合 RAG、微调服务适配、证据规则、终局校验、浏览器入口、结构化界面与评测材料。详见 [三层架构与归属矩阵](docs/ARCHITECTURE_OWNERSHIP.md)。
