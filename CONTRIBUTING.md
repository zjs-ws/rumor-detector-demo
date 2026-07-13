# Contributing

感谢参与 Rumor Detector 的开发。

## 本地开发

1. 从 `.env.example` 创建自己的 `.env`
2. 从 `config.example.yaml` 创建自己的 `config.yaml`
3. 执行 `./scripts/quickstart.sh`
4. 修改完成后执行 `./scripts/doctor.sh`
5. 确认 `git diff --check` 通过后再提交

## 提交前检查

必须确认：

- 没有提交 `.env`
- 没有提交 `config.yaml`
- 没有提交 `runtime/`
- 没有硬编码真实 API Key
- Docker Compose 能正常解析
- README 与配置模板仍然可用

## Commit 示例

- `feat: add browser selection API`
- `fix: stop repeated rumor workflow calls`
- `docs: improve Docker quickstart`
- `test: add rumor result parser tests`
- `chore: update local deployment config`
