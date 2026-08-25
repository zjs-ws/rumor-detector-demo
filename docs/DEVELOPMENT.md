# RumorBuster 开发指南

## 分支与环境

- `main` 是 RumorBuster V2.1 结项归档和 GitHub 默认分支；
- 新工作从默认分支创建独立功能分支，不直接提交运行数据库、密钥或模型权重；
- Python 要求 3.12 及以上；前端使用 Node.js 22、Corepack 和 pnpm；
- Docker 快速启动走 `compose.prod.yaml`，统一入口为 `http://localhost:8080`。

普通应用开发不需要训练数据子模块。复现实验时再运行：

```bash
git submodule update --init --recursive
```

## 初始化

```bash
cp -n .env.example .env
cp -n config.example.yaml config.yaml
make install
corepack pnpm --dir frontend install --frozen-lockfile
```

把 `DEEPSEEK_API_KEY` 和 `TAVILY_API_KEY` 写入本地 `.env`。不要把真实密钥写入示例、测试、日志或 Git 历史。

## 运行方式

面向最终用户或端到端联调：

```bash
./scripts/quickstart.sh
# 或
make up
```

原生开发可分别启动：

```bash
make dev
make gateway
corepack pnpm --dir frontend dev
```

常用生产编排操作：

```bash
make check
make ps
make logs
make stop
```

## 基础检查

```bash
make test
make lint
make frontend-check
node --test browser-extension/tests/*.mjs
git diff --check
```

定向 RumorBuster 回归：

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

不要把历史的 113、127 或 178 项当成永久固定测试数量；以当前命令实际输出和[项目状态](PROJECT_STATUS.md)中的留档日期为准。

## RAG 与评测

```bash
# 校验复核语料
docker compose -f compose.prod.yaml run --rm -T \
  langgraph uv run python scripts/build_rag_index.py --validate-only

# 构建 Chroma 索引
docker compose -f compose.prod.yaml --profile maintenance run --rm rag-indexer

# 对比检索结果
docker compose -f compose.prod.yaml run --rm -T \
  langgraph uv run python scripts/evaluate_rag_retrieval.py --mode hybrid

# 固定离线综合清单
python3 scripts/evaluate_rumorbuster.py
```

真实联网评测、LoRA 模型验收和时间线实验的口径分别见：

- [真实联网验收](REAL_FACTCHECK_ACCEPTANCE.md)
- [LoRA 模型部署](MODELSCOPE_CLASSIFIER_DEPLOYMENT.md)
- [实验手册](LABS.md)

## 使用 DeepSeek 驱动 Claude Code

```bash
./scripts/claude-deepseek.sh
```

脚本读取进程环境、被忽略的 `.claude/deepseek.env` 或根目录 `.env` 中的 `DEEPSEEK_API_KEY`，不会把密钥写入受 Git 跟踪配置。

## 数据与提交边界

允许提交源码、锁文件、配置模板、确定性 Fixture、脱敏报告和小型评测产物。

禁止提交：

- `.env*` 中的真实密钥；
- `config.yaml`；
- `runtime/`、`.deer-flow/` 和 `local-backups/`；
- `.venv/`、`frontend/node_modules/` 和构建缓存；
- `final_result/` 完整模型权重；
- 本地论文、课程 PDF 和未授权材料。

`.dockerignore` 必须与上述安全边界同步，避免本地秘密或大文件通过 `COPY . .` 进入镜像层。
