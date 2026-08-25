# Contributing to RumorBuster

感谢参与 RumorBuster V2.1。默认分支 `main` 是课程结项归档；新改动应从默认分支创建独立功能分支。

## 开始开发

1. 阅读 [README](README.md) 和[开发指南](docs/DEVELOPMENT.md)；
2. 从 `.env.example` 创建本地 `.env`；
3. 从 `config.example.yaml` 创建本地 `config.yaml`；
4. 使用 `./scripts/quickstart.sh` 做端到端联调，或按开发指南分别启动服务；
5. 只修改与当前任务相关的文件，不覆盖他人的本地运行数据。

## 提交前检查

至少执行：

```bash
make check
make lint
make test
make frontend-check
node --test browser-extension/tests/*.mjs
git diff --check
```

若改动只涉及部分组件，可以运行等价的最小相关测试，但需在 PR 中说明未运行的检查及原因。

## 安全与数据边界

不得提交：

- `.env`、`.env.production` 或真实 API Key；
- `config.yaml`、运行日志、会话数据库和检查点；
- `.venv/`、`node_modules/`、`.next/` 或 Docker 缓存；
- 完整模型权重、本地论文和未授权课程资料；
- 含用户原文、模型 reasoning、系统提示词、内部服务地址或密钥的未脱敏报告。

新增本地秘密或大型生成目录时，同时更新 `.gitignore` 与 `.dockerignore`。

## 文档同步

- 用户可见行为、启动方式或配置变化必须更新 `README.md`；
- 架构、工作流、命令或开发约束变化必须更新 `CLAUDE.md` 或对应 `docs/` 文档；
- 评测数字必须标注日期、数据规模、运行层级和限制，不能把模型离线指标写成系统准确率。

## Commit 与 PR

建议使用清晰的 Conventional Commit 风格：

- `feat: add browser selection API`
- `fix: preserve fetched evidence provenance`
- `docs: clarify production quickstart`
- `test: add verdict boundary cases`
- `chore: update local deployment config`

PR 描述应包括问题、解决方式、验证命令、兼容性影响和任何仍未解决的边界。
