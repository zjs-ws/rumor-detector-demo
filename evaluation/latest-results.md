# RumorBuster 离线评测结果

| 指标 | 结果 |
|---|---:|
| checkability_accuracy | 1.0000 |
| rag_recall_at_3 | 1.0000 |
| workflow_stage_accuracy | 1.0000 |
| full_rule_accuracy | 1.0000 |
| classifier_only_accuracy | 0.0000 |
| without_time_check_accuracy | 0.8000 |
| without_independence_check_accuracy | 0.9333 |

## 裁决案例

| 案例 | 预期 | 完整规则 | 仅分类器 | 去时效校验 | 去独立性校验 |
|---|---|---|---|---|---|
| decision-a-refute | 谣言 | 谣言 | 非谣言 | 谣言 | 谣言 |
| decision-two-b-support | 非谣言 | 非谣言 | 谣言 | 非谣言 | 非谣言 |
| decision-duplicate-b | 证据不足 | 证据不足 | 谣言 | 证据不足 | 谣言 |
| decision-a-conflict | 存疑 | 存疑 | 非谣言 | 存疑 | 存疑 |
| decision-stale-a | 证据不足 | 证据不足 | 非谣言 | 非谣言 | 证据不足 |
| decision-snippet-a | 证据不足 | 证据不足 | 谣言 | 证据不足 | 证据不足 |
| decision-authority-mismatch | 证据不足 | 证据不足 | 非谣言 | 证据不足 | 证据不足 |
| decision-two-b-refute | 谣言 | 谣言 | 非谣言 | 谣言 | 谣言 |
| decision-a-over-b | 非谣言 | 非谣言 | 谣言 | 非谣言 | 非谣言 |
| decision-unknown-date | 证据不足 | 证据不足 | 非谣言 | 非谣言 | 证据不足 |
| decision-historical-event | 谣言 | 谣言 | 非谣言 | 谣言 | 谣言 |
| decision-current-old-guidance | 证据不足 | 证据不足 | 非谣言 | 非谣言 | 证据不足 |
| decision-ordinary-page-downgrade | 证据不足 | 证据不足 | 非谣言 | 证据不足 | 证据不足 |
| decision-mixed-subclaims | 误导 | 误导 | 谣言 | 误导 | 误导 |
| decision-incomplete-subclaims | 证据不足 | 证据不足 | 非谣言 | 证据不足 | 证据不足 |

> 这些案例是覆盖冲突、过时、重复转载、来源降级和混合子主张的对抗式规则回归集；仅分类器指标不能代表自然分布总体准确率。该离线评测也不替代真实网页检索端到端评测。
