# RumorBuster 离线评测结果

| 指标 | 结果 |
|---|---:|
| checkability_accuracy | 1.0000 |
| rag_recall_at_3 | 1.0000 |
| workflow_stage_accuracy | 1.0000 |
| full_rule_accuracy | 1.0000 |
| classifier_only_accuracy | 0.0000 |
| without_time_check_accuracy | 0.8333 |
| without_independence_check_accuracy | 0.9444 |
| v3_comprehensive_component_accuracy | 1.0000 |

## V3 40 条综合清单

| 类别 | 组件正确率 |
|---|---:|
| checkability_boundary | 1.0000 |
| verified_rumor_rag | 1.0000 |
| evidence_conflict_and_professional | 1.0000 |
| mixed_subclaims | 1.0000 |
| url_and_failure_flow | 1.0000 |

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
| decision-all-subclaims-supported | 非谣言 | 非谣言 | 谣言 | 非谣言 | 非谣言 |
| decision-all-subclaims-refuted | 谣言 | 谣言 | 非谣言 | 谣言 | 谣言 |
| decision-three-subclaims-one-missing | 证据不足 | 证据不足 | 谣言 | 证据不足 | 证据不足 |

> V3 40 条清单按课程计划固定为 10 条可核验性边界、8 条旧谣言 RAG、12 条证据冲突/过时/专业规则、5 条混合子主张和 5 条 URL/故障路由。它复用可重复的组件样本，不等于 40 次实时联网端到端运行。仅分类器指标不能代表自然分布总体准确率，离线结果也不替代三个真实网页演示。
