# RumorBuster

面向网页端与浏览器划词插件的谣言检测智能体。

用户可以在网页端粘贴新闻、社交媒体消息或其他文本进行核验，也可以通过浏览器扩展选中文字并直接进入核验工作区。当前分支已提供 RumorBuster 网页端、浏览器划词入口、智能体后端、API Gateway、模型调用与本地持久化能力。

## 当前状态

已验证：

- Docker Compose 本地部署
- RumorBuster Next.js 网页端
- DeepSeek 模型调用
- 谣言检测智能体基础对话
- API Gateway 健康检查
- SQLite 会话与检查点持久化
- 无需额外密钥、保留原始搜索结果且最长 60 秒的 DuckDuckGo 公开网页检索
- 输入公开网页 URL 后抓取正文，并在报告中生成可点击、可追溯的来源引用
- 运行时校验最终引用：移除本轮工具未返回的链接；未引用独立外部来源时，自动降级为“存疑（证据不足）/低证据强度”
- Chrome 浏览器划词核验入口
- Apple Silicon Docker 环境

继续开发中：

- 注册与登录系统
- 更稳定的可选搜索提供商与网页原文抓取
- RAG 知识库
- 微调谣言分类模型服务
- 完整外部证据链与结果归档
- 生产环境鉴权

> 当前版本为开发预览版，不建议直接暴露到公网。

## 快速启动

1. 克隆并进入项目：

   `git clone -b enhanced_one https://github.com/zjs-ws/rumor-detector-demo.git`

   `cd rumor-detector-demo`

2. 创建本地配置：

   `cp -n .env.example .env`

   `cp -n config.example.yaml config.yaml`

3. 编辑 `.env`，填写自己的 `DEEPSEEK_API_KEY`。

   网页正文抓取默认使用受大小、超时、重定向和公网地址约束的本地读取；如需
   更稳定的复杂网页解析，可选填 `JINA_API_KEY` 启用 Jina Reader。

4. 一键启动：

   `./scripts/quickstart.sh`

## 安装浏览器划词扩展

1. 启动 RumorBuster，确认 `http://localhost:3000` 可以访问。
2. 在 Chrome 打开 `chrome://extensions`。
3. 开启“开发者模式”，点击“加载已解压的扩展程序”。
4. 选择仓库中的 `browser-extension/` 目录。
5. 在任意网页选中文字，右键选择“用 RumorBuster 核验”。

扩展会打开新对话并预填原文与来源页面，不会自动发送。选中文字通过 URL
fragment 传递，不会进入本地服务的 HTTP 请求或访问日志；前端读取后会立即
清除地址栏中的 fragment。

## 服务地址

- RumorBuster 网页端：`http://localhost:3000`
- Gateway 健康检查：`http://localhost:8001/health`
- Gateway API 文档：`http://localhost:8001/docs`
- 内部智能体开发接口：`http://localhost:2024/docs`

`2024` 端口仅用于后端开发调试，不应直接暴露给最终用户。

## 常用命令

- 查看状态：`docker compose ps`
- 查看日志：`docker compose logs -f`
- 重新构建：`docker compose up -d --build --force-recreate`
- 停止服务：`docker compose down`
- 环境检查：`./scripts/doctor.sh`
- URL 核验端到端冒烟测试：`docker compose run --rm -T -v "$PWD/scripts:/app/scripts:ro" -e LANGGRAPH_BASE_URL=http://langgraph:2024 langgraph uv run python scripts/smoke_url_factcheck.py`

## 配置安全

可以提交：

- `.env.example`
- `config.example.yaml`
- `compose.yaml`
- `Dockerfile.local`

禁止提交：

- `.env`
- `config.yaml`
- `runtime/`
- `local-backups/`

每位开发者使用自己的 API Key。真实密钥只保存在本地 `.env` 中。

## 项目结构

- `app/`：API Gateway 与消息通道
- `packages/harness/`：智能体运行核心
- `packages/harness/deerflow/agents/rumor_agent/`：谣言检测智能体
- `frontend/`：RumorBuster Next.js 网页端
- `browser-extension/`：Chrome Manifest V3 划词核验扩展
- `compose.yaml`：本地 Docker 编排
- `Dockerfile.local`：本地开发镜像
- `scripts/quickstart.sh`：一键启动
- `scripts/doctor.sh`：环境与安全检查

## 已知限制

1. 默认只配置 DeepSeek 主模型。
2. 微调分类模型服务尚未包含在 Compose 中。
3. 默认联网核验使用 DuckDuckGo 搜索结果摘要，并限制为单个研究子任务、1 次工具调用、最长 60 秒。研究任务直接返回原始结构化结果，避免中间模型改写来源；搜索失败时系统会明确降级为文本分析。
4. 智能体已加入模型/工具调用上限，后续仍需补齐真实证据源后的复杂流程测试。
5. 当前智能体服务使用本地开发模式和无鉴权配置。
6. 注册登录尚未接入；浏览器扩展当前为本地加载版，默认连接 `http://localhost:3000`。
7. 每轮最多抓取用户提供的 1 个公开 HTTP(S) URL，正文最多保留 12,000 个字符。登录墙、强动态渲染或阻止爬取的网页可能无法读取；私网、localhost 与非 HTTP(S) 地址会被拒绝。

## 产品方向

独立网页端和浏览器划词扩展共用同一套新对话流程。浏览器入口只负责安全地预填待核验内容，实际提交仍由用户确认。包含 URL 的核验请求会先读取原网页，再搜索独立来源交叉核查；报告中的引用必须来自本轮实际抓取或搜索结果。后端会在最终输出阶段再次校验引用来源：未出现在工具证据中的链接不会作为可点击引用保留，报告没有引用至少一个独立检索来源时也不能输出确定性结论或高证据强度。
