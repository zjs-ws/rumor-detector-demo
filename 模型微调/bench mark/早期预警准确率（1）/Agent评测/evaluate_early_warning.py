"""
Agent 早期预警准确率 —— 批量测试脚本

读取上级目录中 build_early_warning_testset.py 生成的纯文本测试集，
逐条发送到 Agent FastAPI 接口，对比返回结果与真实标签，
输出早期预警准确率及详细评估报告。

用法:
    python3 evaluate_early_warning.py                                      # 使用默认地址
    python3 evaluate_early_warning.py --api http://x.x.x.x:8000/detect    # 指定接口
    python3 evaluate_early_warning.py --limit 10                           # 先测 10 条

输出:
    早期预警评估报告.txt   —— 完整评估报告（含分类别指标）
    早期预警逐条结果.json  —— 每条数据的详细预测结果
"""

import json
import time
import argparse
import os
import sys
from collections import defaultdict

try:
    import requests
except ImportError:
    print("❌ 缺少 requests 库，请先执行: pip install requests")
    sys.exit(1)

# ======================== 配置 ========================
DEFAULT_API_URL = "http://127.0.0.1:8000/detect"
TESTSET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "早期预警测试集.json")
OUTPUT_REPORT = "早期预警评估报告.txt"
OUTPUT_DETAIL = "早期预警逐条结果.json"
REQUEST_TIMEOUT = 60


def parse_agent_response(response_json: dict) -> dict:
    """
    解析 Agent 接口的返回值。

    适配以下两种常见返回格式，请根据你们实际接口的返回结构修改此函数：

    格式 A（带 risk_score）:
        {"conclusion": "rumor", "risk_score": 0.92, "reason": "..."}

    格式 B（纯标签）:
        {"result": "Yes"}  或  {"label": "rumor"}  或  {"output": "Yes"}
    """
    LABEL_NORMALIZE = {
        "yes": "rumor",
        "no": "non_rumor",
        "unknown": "unknown",
        "rumor": "rumor",
        "non_rumor": "non_rumor",
        "non-rumor": "non_rumor",
        "not rumor": "non_rumor",
        "真实": "non_rumor",
        "谣言": "rumor",
        "未知": "unknown",
    }

    conclusion = (
        response_json.get("conclusion")
        or response_json.get("result")
        or response_json.get("label")
        or response_json.get("output")
        or response_json.get("prediction")
        or ""
    )
    conclusion = LABEL_NORMALIZE.get(conclusion.strip().lower(), conclusion.strip().lower())

    risk_score = response_json.get("risk_score", response_json.get("score", None))
    if risk_score is not None:
        risk_score = float(risk_score)

    reason = response_json.get("reason", response_json.get("explanation", ""))

    return {
        "predicted_label": conclusion,
        "risk_score": risk_score,
        "reason": reason,
    }


def call_agent_api(text: str, api_url: str) -> dict:
    """向 Agent 发送单条检测请求"""
    payload = {"text": text}
    resp = requests.post(api_url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ======================== 指标计算 ========================

def compute_metrics(results: list[dict]) -> dict:
    total = len(results)
    correct = sum(1 for r in results if r["match"])
    accuracy = correct / total if total else 0.0

    labels = sorted(set(r["true_label"] for r in results))
    per_label = {}
    for label in labels:
        subset = [r for r in results if r["true_label"] == label]
        tp = sum(1 for r in subset if r["match"])
        per_label[label] = {
            "total": len(subset),
            "correct": tp,
            "accuracy": tp / len(subset) if subset else 0.0,
        }

    precision_recall = {}
    for label in labels:
        tp = sum(1 for r in results if r["true_label"] == label and r["predicted_label"] == label)
        fp = sum(1 for r in results if r["true_label"] != label and r["predicted_label"] == label)
        fn = sum(1 for r in results if r["true_label"] == label and r["predicted_label"] != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        precision_recall[label] = {"precision": precision, "recall": recall, "f1": f1}

    confusion = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r["true_label"]][r["predicted_label"]] += 1

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "per_label_accuracy": per_label,
        "precision_recall_f1": precision_recall,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "all_labels": labels,
    }


def format_report(metrics: dict, elapsed: float, api_url: str) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("    谣言智能体 · 早期预警准确率 评估报告")
    lines.append("=" * 60)
    lines.append(f"  接口地址:          {api_url}")
    lines.append(f"  方法:              Agent 智能体（完整架构）")
    lines.append(f"  测试样本数:        {metrics['total']}")
    lines.append(f"  正确预测数:        {metrics['correct']}")
    lines.append(f"  总体准确率:        {metrics['accuracy']:.1%}")
    lines.append(f"  总耗时:            {elapsed:.1f}s")
    lines.append(f"  平均每条耗时:      {elapsed / metrics['total']:.2f}s")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  分类别准确率:")
    lines.append(f"  {'标签':>12s}  {'样本数':>6s}  {'正确':>4s}  {'准确率':>8s}")
    lines.append("  " + "-" * 40)
    for label, info in sorted(metrics["per_label_accuracy"].items()):
        lines.append(
            f"  {label:>12s}  {info['total']:>6d}  {info['correct']:>4d}  {info['accuracy']:>8.1%}"
        )
    lines.append("")

    lines.append("-" * 60)
    lines.append("  Precision / Recall / F1:")
    lines.append(f"  {'标签':>12s}  {'Precision':>10s}  {'Recall':>8s}  {'F1':>8s}")
    lines.append("  " + "-" * 44)
    for label, info in sorted(metrics["precision_recall_f1"].items()):
        lines.append(
            f"  {label:>12s}  {info['precision']:>10.3f}  {info['recall']:>8.3f}  {info['f1']:>8.3f}"
        )
    lines.append("")

    lines.append("-" * 60)
    lines.append("  混淆矩阵 (行=真实, 列=预测):")
    all_labels = metrics["all_labels"]
    header = f"  {'':>12s}  " + "  ".join(f"{l:>10s}" for l in all_labels)
    lines.append(header)
    lines.append("  " + "-" * (14 + 12 * len(all_labels)))
    for true_label in all_labels:
        row_data = metrics["confusion"].get(true_label, {})
        row = f"  {true_label:>12s}  " + "  ".join(
            f"{row_data.get(pl, 0):>10d}" for pl in all_labels
        )
        lines.append(row)
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(description="Agent 早期预警准确率批量评测")
    parser.add_argument("--api", default=DEFAULT_API_URL, help="Agent 检测接口地址")
    parser.add_argument("--testset", default=TESTSET_FILE, help="测试集 JSON 文件路径")
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 条 (0=全部)")
    args = parser.parse_args()

    testset_path = os.path.abspath(args.testset)

    if not os.path.exists(testset_path):
        print(f"❌ 测试集文件不存在: {testset_path}")
        print("   请先在上级目录运行: python3 build_early_warning_testset.py")
        sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[: args.limit]

    print(f"📋 测试集已加载: {len(test_data)} 条记录")
    print(f"🌐 目标接口: {args.api}")
    print(f"📌 方法: Agent 智能体（完整架构）")
    print("=" * 50)

    results = []
    errors = []
    t_start = time.time()

    for idx, item in enumerate(test_data):
        text = item["text"]
        true_label = item["true_label"]
        display_text = text[:40] + ("..." if len(text) > 40 else "")

        try:
            raw_response = call_agent_api(text, args.api)
            parsed = parse_agent_response(raw_response)
            match = parsed["predicted_label"] == true_label

            record = {
                "index": idx,
                "text": text,
                "true_label": true_label,
                "predicted_label": parsed["predicted_label"],
                "risk_score": parsed["risk_score"],
                "reason": parsed["reason"],
                "match": match,
            }
            results.append(record)

            status = "✅" if match else "❌"
            score_str = f" (score={parsed['risk_score']:.2f})" if parsed["risk_score"] is not None else ""
            print(
                f"  [{idx + 1:3d}/{len(test_data)}] {status} "
                f"真实={true_label:10s} 预测={parsed['predicted_label']:10s}{score_str}  {display_text}"
            )

        except requests.exceptions.ConnectionError:
            print(f"  [{idx + 1:3d}/{len(test_data)}] 🔴 连接失败 — 请确认 Agent 接口已启动")
            errors.append({"index": idx, "text": text, "error": "ConnectionError"})
        except requests.exceptions.Timeout:
            print(f"  [{idx + 1:3d}/{len(test_data)}] 🔴 超时 ({REQUEST_TIMEOUT}s)")
            errors.append({"index": idx, "text": text, "error": "Timeout"})
        except Exception as e:
            print(f"  [{idx + 1:3d}/{len(test_data)}] 🔴 异常: {e}")
            errors.append({"index": idx, "text": text, "error": str(e)})

    elapsed = time.time() - t_start
    print(f"\n{'=' * 50}")

    if not results:
        print("❌ 无有效结果，请检查 Agent 接口连接")
        sys.exit(1)

    metrics = compute_metrics(results)
    report = format_report(metrics, elapsed, args.api)
    print(report)

    script_dir = os.path.dirname(os.path.abspath(__file__))

    report_path = os.path.join(script_dir, OUTPUT_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_path = os.path.join(script_dir, OUTPUT_DETAIL)
    detail_output = {"metrics_summary": metrics, "results": results, "errors": errors}
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 逐条结果已保存: {detail_path}")

    if errors:
        print(f"\n⚠️  共 {len(errors)} 条请求失败，详见逐条结果文件")


if __name__ == "__main__":
    main()
