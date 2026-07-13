# Rumor Detector

面向网页端与浏览器划词插件的谣言检测智能体。

用户可以在网页端粘贴新闻、社交媒体消息或其他文本进行核验；后续也可通过浏览器插件选中文字并直接发起检测。当前分支已提供 RumorBuster 网页端、智能体后端、API Gateway、模型调用与本地持久化能力。

## 当前状态

已验证：

- Docker Compose 本地部署
- RumorBuster Next.js 网页端
- DeepSeek 模型调用
- 谣言检测智能体基础对话
- API Gateway 健康检查
- SQLite 会话与检查点持久化
- Apple Silicon Docker 环境

继续开发中：

- 注册与登录系统
- 浏览器划词插件
- 联网搜索与证据检索
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

4. 一键启动：

   `./scripts/quickstart.sh`

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
- `compose.yaml`：本地 Docker 编排
- `Dockerfile.local`：本地开发镜像
- `scripts/quickstart.sh`：一键启动
- `scripts/doctor.sh`：环境与安全检查

## 已知限制

1. 默认只配置 DeepSeek 主模型。
2. 微调分类模型服务尚未包含在 Compose 中。
3. 真实联网检索与完整 RAG 工具尚未启用；未配置时系统只进行文本分析并明确说明能力边界。
4. 智能体已加入模型/工具调用上限，后续仍需补齐真实证据源后的复杂流程测试。
5. 当前智能体服务使用本地开发模式和无鉴权配置。
6. 注册登录与浏览器插件尚未在本分支提供。

## 产品方向

最终提供独立网页端和浏览器划词插件。两种入口统一通过产品 API 调用后端，普通用户不会接触内部智能体编排、节点图或开发调试平台。
