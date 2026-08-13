# RumorBuster V2/V3 演示运行摘要

生成时间：2026-08-12T14:22:06.263689+00:00

| 图 | 案例 | 次数 | 状态 | 结论 | 领域 | 耗时(ms) | 校验 |
|---|---|---:|---|---|---|---:|---|
| rumor_agent | boundary-opinion | 1 | completed | 非事实性表达 | general | 1513 | 通过 |
| rumor_agent | medical-old-rumor | 1 | completed | 证据不足 | medical | 19190 | 通过 |
| rumor_agent | science-url-claim | 1 | completed | 证据不足 | science | 32132 | 通过 |

> 每次运行使用独立线程；文件不保存 thread_id、密钥或完整环境变量。
