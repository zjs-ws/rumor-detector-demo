#!/usr/bin/env python3
"""Run deterministic offline RumorBuster metrics and ablations."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.agents.middlewares.rumor_workflow_middleware import derive_workflow
from deerflow.agents.rumor_agent.claim_router import assess_checkability
from deerflow.agents.rumor_agent.evidence import decide_evidence
from deerflow.agents.rumor_agent.rag import retrieve_verified_rumors

ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 0.0


def evaluate() -> dict:
    route_cases = _jsonl(ROOT / "evaluation/checkability_cases.jsonl")
    route_results = {case["id"]: assess_checkability(case["claim"]).checkability.value == case["expected"] for case in route_cases}
    route_correct = sum(route_results.values())

    rag_cases = _jsonl(ROOT / "evaluation/rag_cases.jsonl")
    rag_hits = 0
    rag_results: dict[str, bool] = {}
    for case in rag_cases:
        result = retrieve_verified_rumors(case["claim"], threshold=0.05)
        hit = case["expected_record_id"] in {match.record_id for match in result.matches}
        rag_results[case["id"]] = hit
        rag_hits += hit

    workflow_cases = json.loads((ROOT / "evaluation/workflow_cases.json").read_text(encoding="utf-8"))
    workflow_correct = 0
    workflow_results: dict[str, bool] = {}
    for case in workflow_cases:
        messages = []
        for raw in case["messages"]:
            if raw["type"] == "human":
                messages.append(HumanMessage(content=raw["content"]))
            else:
                messages.append(
                    ToolMessage(
                        name=raw["name"],
                        tool_call_id=raw["tool_call_id"],
                        content=raw["content"],
                    )
                )
        capabilities = case["capabilities"]
        workflow = derive_workflow(
            {"messages": messages},
            web_search_enabled=capabilities["web_search"],
            web_fetch_enabled=capabilities["web_fetch"],
            classifier_enabled=capabilities["classifier"],
        )
        correct = workflow["stage"] == case["expected_stage"]
        workflow_results[case["id"]] = correct
        workflow_correct += correct

    decision_cases = json.loads((ROOT / "evaluation/decision_cases.json").read_text(encoding="utf-8"))
    rule_correct = 0
    classifier_correct = 0
    no_time_correct = 0
    no_independence_correct = 0
    decision_results: dict[str, bool] = {}
    details = []
    for case in decision_cases:
        signal = {"status": "ok", "label": case["classifier_label"], "authoritative": False}
        decision = decide_evidence(
            evidence=case["evidence"],
            classifier_signal=signal,
            claim_context=case.get("claim_context"),
        )
        classifier_verdict = "谣言" if case["classifier_label"] == "rumor" else "非谣言"

        no_time = deepcopy(case["evidence"])
        for item in no_time:
            item["temporal_relevance"] = "current"
        no_time_verdict = decide_evidence(
            evidence=no_time,
            claim_context=case.get("claim_context"),
            enforce_time=False,
        ).verdict

        no_independence = deepcopy(case["evidence"])
        no_independence_verdict = decide_evidence(
            evidence=no_independence,
            claim_context=case.get("claim_context"),
            enforce_independence=False,
        ).verdict

        decision_correct = decision.verdict == case["expected"]
        decision_results[case["id"]] = decision_correct
        rule_correct += decision_correct
        classifier_correct += classifier_verdict == case["expected"]
        no_time_correct += no_time_verdict == case["expected"]
        no_independence_correct += no_independence_verdict == case["expected"]
        details.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "full_rules": decision.verdict,
                "classifier_only": classifier_verdict,
                "without_time_check": no_time_verdict,
                "without_independence_check": no_independence_verdict,
            }
        )

    component_results = {
        "checkability": route_results,
        "rag": rag_results,
        "decision": decision_results,
        "workflow": workflow_results,
    }
    comprehensive_cases = json.loads((ROOT / "evaluation/v3_comprehensive_cases.json").read_text(encoding="utf-8"))
    comprehensive_details: list[dict[str, Any]] = []
    category_totals: dict[str, dict[str, int]] = {}
    for case in comprehensive_cases:
        component = case["component"]
        case_id = case["case_id"]
        if component not in component_results or case_id not in component_results[component]:
            raise ValueError(f"Unknown comprehensive evaluation reference: {component}/{case_id}")
        correct = component_results[component][case_id]
        category = case["category"]
        totals = category_totals.setdefault(category, {"correct": 0, "total": 0})
        totals["correct"] += int(correct)
        totals["total"] += 1
        comprehensive_details.append({**case, "correct": correct})

    comprehensive_correct = sum(item["correct"] for item in comprehensive_details)
    category_metrics = {name: _accuracy(values["correct"], values["total"]) for name, values in category_totals.items()}

    return {
        "dataset": {
            "checkability": len(route_cases),
            "rag": len(rag_cases),
            "decision": len(decision_cases),
            "workflow": len(workflow_cases),
            "v3_comprehensive_manifest": len(comprehensive_cases),
        },
        "metrics": {
            "checkability_accuracy": _accuracy(route_correct, len(route_cases)),
            "rag_recall_at_3": _accuracy(rag_hits, len(rag_cases)),
            "workflow_stage_accuracy": _accuracy(workflow_correct, len(workflow_cases)),
            "full_rule_accuracy": _accuracy(rule_correct, len(decision_cases)),
            "classifier_only_accuracy": _accuracy(classifier_correct, len(decision_cases)),
            "without_time_check_accuracy": _accuracy(no_time_correct, len(decision_cases)),
            "without_independence_check_accuracy": _accuracy(no_independence_correct, len(decision_cases)),
            "v3_comprehensive_component_accuracy": _accuracy(comprehensive_correct, len(comprehensive_cases)),
        },
        "v3_category_metrics": category_metrics,
        "v3_comprehensive_details": comprehensive_details,
        "decision_details": details,
    }


def _markdown(result: dict) -> str:
    metrics = result["metrics"]
    lines = [
        "# RumorBuster 离线评测结果",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        *[f"| {name} | {value:.4f} |" for name, value in metrics.items()],
        "",
        "## V3 40 条综合清单",
        "",
        "| 类别 | 组件正确率 |",
        "|---|---:|",
        *[f"| {name} | {value:.4f} |" for name, value in result["v3_category_metrics"].items()],
        "",
        "## 裁决案例",
        "",
        "| 案例 | 预期 | 完整规则 | 仅分类器 | 去时效校验 | 去独立性校验 |",
        "|---|---|---|---|---|---|",
    ]
    for item in result["decision_details"]:
        lines.append(f"| {item['id']} | {item['expected']} | {item['full_rules']} | {item['classifier_only']} | {item['without_time_check']} | {item['without_independence_check']} |")
    lines.extend(
        [
            "",
            (
                "> V3 40 条清单按课程计划固定为 10 条可核验性边界、8 条旧谣言 RAG、12 条证据冲突/过时/专业规则、"
                "5 条混合子主张和 5 条 URL/故障路由。它复用可重复的组件样本，不等于 40 次实时联网端到端运行。"
                "仅分类器指标不能代表自然分布总体准确率，离线结果也不替代三个真实网页演示。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/results/latest.json")
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(result), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
