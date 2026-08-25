# RumorBuster 文档

这里同时包含 RumorBuster 领域实现文档和上游 DeerFlow 通用文档。第一次接手项目时，优先阅读“开始与开发”和“架构与工作流”。

## 开始与开发

| 文档 | 内容 |
|---|---|
| [项目 README](../README.md) | 项目简介与五分钟启动 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 开发环境、命令、测试和提交边界 |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | 结项基线、验证口径和未完成项 |
| [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) | 生产编排、备份、恢复和排错 |
| [CONFIGURATION.md](CONFIGURATION.md) | 通用配置项 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | 贡献流程 |

## 架构与工作流

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE_OWNERSHIP.md](ARCHITECTURE_OWNERSHIP.md) | LangGraph、DeerFlow 与 RumorBuster 三层归属 |
| [WORKFLOW_V3_IMPLEMENTATION.md](WORKFLOW_V3_IMPLEMENTATION.md) | 当前 V3 显式 StateGraph 与并行取证 |
| [WORKFLOW_V2_IMPLEMENTATION.md](WORKFLOW_V2_IMPLEMENTATION.md) | 保留的 V2 阶段门控流程 |
| [RAG_IMPLEMENTATION.md](RAG_IMPLEMENTATION.md) | Loader、切片、Embedding、Chroma 和混合召回 |
| [PAPER_TO_IMPLEMENTATION.md](PAPER_TO_IMPLEMENTATION.md) | 论文启发、落地内容和不应宣称的边界 |
| [SOCIAL_CONTEXT_FUTURE.md](SOCIAL_CONTEXT_FUTURE.md) | 未启用的评论质证扩展 |

## API、运维与安全

| 文档 | 内容 |
|---|---|
| [API.md](API.md) | DeerFlow/Gateway API 参考 |
| [FILE_UPLOAD.md](FILE_UPLOAD.md) | 文件上传能力 |
| [PATH_EXAMPLES.md](PATH_EXAMPLES.md) | 路径与 Sandbox 示例 |
| [SECURITY.md](../SECURITY.md) | 安全说明 |
| [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md) | 历史工程交接记录 |

## 评测与实验

| 文档 | 内容 |
|---|---|
| [REAL_FACTCHECK_ACCEPTANCE.md](REAL_FACTCHECK_ACCEPTANCE.md) | 真实联网验收标准 |
| [FINETUNED_3B_EVALUATION.md](FINETUNED_3B_EVALUATION.md) | Qwen2.5-3B LoRA 离线指标及限制 |
| [MODELSCOPE_CLASSIFIER_DEPLOYMENT.md](MODELSCOPE_CLASSIFIER_DEPLOYMENT.md) | 独立 GPU 服务部署与验收 |
| [LABS.md](LABS.md) | 日志、并行、状态和消融实验 |
| [DEFENSE_STUDY_GUIDE.md](DEFENSE_STUDY_GUIDE.md) | 课程答辩源码学习材料 |

## 课程归档

| 文档 | 内容 |
|---|---|
| [COURSE_PROJECT_PLAN.md](COURSE_PROJECT_PLAN.md) | 历史课程计划 |
| [TEAM_CONTRIBUTIONS.md](TEAM_CONTRIBUTIONS.md) | 团队贡献与交付记录 |
| [DEFENSE_A_STUDY_PACK.md](DEFENSE_A_STUDY_PACK.md) | 成员 A 答辩问答资料 |
| [DEFENSE_A_MOCKS.md](DEFENSE_A_MOCKS.md) | 模拟问答 |
| [DEFENSE_A_DAY_OF_CARD.md](DEFENSE_A_DAY_OF_CARD.md) | 答辩速查页 |

## 上游 DeerFlow 通用文档

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SETUP.md](SETUP.md)
- [AUTO_TITLE_GENERATION.md](AUTO_TITLE_GENERATION.md)
- [summarization.md](summarization.md)
- [plan_mode_usage.md](plan_mode_usage.md)
- [TODO.md](TODO.md)
