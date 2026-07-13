# Security Policy

## 密钥安全

本项目不接受任何真实 API Key、密码、Token 或私有证书进入仓库。

开发者应：

- 从 `.env.example` 创建 `.env`
- 只在本地 `.env` 中保存密钥
- 提交前运行 `./scripts/doctor.sh`
- 不在 Issue、日志或截图中公开真实密钥

若真实密钥被意外提交：

1. 立即撤销旧密钥
2. 生成新密钥
3. 清理当前提交与 Git 历史
4. 通知项目维护者
