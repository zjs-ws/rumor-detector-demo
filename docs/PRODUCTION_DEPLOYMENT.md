# RumorBuster 单机生产部署

第一阶段采用单机 Docker Compose。公网只访问 Nginx；Frontend、Gateway 和 LangGraph 不发布宿主机端口。当前版本没有登录与生产鉴权，正式开放公网前必须在云防火墙、VPN 或上游反向代理中限制访问，并配置 HTTPS。

## 1. 准备

服务器需要 Docker Engine、Docker Compose v2、Git，以及可访问所选模型和搜索服务的网络。

```bash
cp .env.production.example .env.production
cp config.example.yaml config.yaml
```

在 `.env.production` 中填写真实密钥；不要提交该文件。生产配置会优先采用 `.env.production`，本机若仅有旧版 `.env` 也可用于验收。模型、搜索和可选微调服务仍由 `config.yaml` 与环境变量控制。微调服务未配置时系统会跳过该能力。

## 2. 启动与验收

```bash
docker compose -f compose.prod.yaml config
docker compose -f compose.prod.yaml up -d --build
docker compose -f compose.prod.yaml ps
python3 scripts/check_production_ready.py
```

默认入口是 `http://服务器地址:8080`，可通过 `RUMORBUSTER_HTTP_PORT` 修改。聚合就绪检查 `GET /healthz` 只确认 Gateway 能访问 `rumor_agent`，不会调用外部模型。

业务 API 示例：

```bash
curl -X POST http://localhost:8080/api/v1/checks \
  -H 'Content-Type: application/json' \
  -d '{"claim":"某市已经发布新的公共交通规定","source_url":"https://example.com/article"}'

curl http://localhost:8080/api/v1/checks/替换为check_id
```

同步调用最多等待 120 秒。超时时返回 HTTP 504 和 `check_id`；Gateway 断开等待后 LangGraph 运行继续，调用方可通过查询接口继续观察。查询未完成时 `status` 为 `running`，并返回当前 `workflow.stage`。OpenAPI 文档位于 `/api/docs`。

## 3. 日常操作

```bash
# 日志
docker compose -f compose.prod.yaml logs -f --tail=200 nginx gateway langgraph frontend

# 停止（不删除 runtime）
docker compose -f compose.prod.yaml down

# 更新
git pull --ff-only
docker compose -f compose.prod.yaml up -d --build

# 状态与就绪检查
docker compose -f compose.prod.yaml ps
curl -fsS http://localhost:8080/healthz
```

只有 Nginx 应出现 `HOST:PORT->80` 映射。LangGraph 流式接口为 `/api/langgraph/*`，Nginx 已关闭响应和请求缓冲，并把读写超时设置为 120 秒；上游服务地址通过 Docker DNS 动态解析，单个容器重建后无需重启 Nginx。

## 4. 备份与恢复

线程检查点、线程目录和报告都位于 `runtime/`。备份前先停服务，避免复制到一半的 SQLite 文件。

```bash
docker compose -f compose.prod.yaml down
mkdir -p local-backups
tar -czf local-backups/rumorbuster-runtime.tar.gz runtime
docker compose -f compose.prod.yaml up -d
```

恢复时先停止服务，保留当前目录作为可回退副本，再解压备份：

```bash
docker compose -f compose.prod.yaml down
mv runtime runtime.before-restore
tar -xzf local-backups/rumorbuster-runtime.tar.gz
docker compose -f compose.prod.yaml up -d
python3 scripts/check_production_ready.py
```

确认恢复成功后再人工清理 `runtime.before-restore`。

## 5. 故障与回滚

- `Gateway 503`：查看 Gateway 与 LangGraph 日志，确认 `LANGGRAPH_INTERNAL_URL=http://langgraph:2024` 且 `rumor_agent` 已注册。
- `POST 504`：模型或研究过程超过同步等待时间；保留 `check_id` 并继续调用 GET。
- 搜索失败：报告应带 `research_unavailable` 等降级标记，规则裁决仍会执行。
- 磁盘增长：重点检查 `runtime/checkpoints/` 与 `runtime/threads/`，备份后再按线程清理。
- 页面有响应但流式内容延迟：确认请求进入 `/api/langgraph/`，并检查 Nginx 配置中的 `proxy_buffering off`。
- 回滚：切回上一个已验证提交或镜像标签，再执行 `docker compose -f compose.prod.yaml up -d --build`；`runtime/` 不随代码回滚删除。

生产公网还应在 Nginx 前配置 HTTPS、访问频率限制和访问控制。注册登录、Postgres、多机扩容、微调模型容器和 MCP 均属于后续增强，不进入本阶段关键路径。

> 当前 Compose 中的 LangGraph 使用开源 `langgraph dev` 本地运行时和项目自带 SQLite Checkpointer，适合课程演示与单机受限访问部署。它不等同于 LangGraph 官方托管/企业生产运行时；若面向大量公网用户，应升级依赖并迁移到受支持的 LangGraph 部署或自建等价运行服务，同时改用 Postgres、鉴权和限流。
