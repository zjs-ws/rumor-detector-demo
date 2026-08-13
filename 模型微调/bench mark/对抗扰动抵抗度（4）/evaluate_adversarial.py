"""
对抗扰动抵抗度 —— 第二步：在脏数据上评测 Agent 和基线

读取对抗测试集，分别发给 Agent 接口和裸 LLM 基线，
收集两者在"脏数据"上的表现。

用法:
    # 测 Agent
    python3 evaluate_adversarial.py agent --api http://127.0.0.1:8000/detect
    python3 evaluate_adversarial.py agent --limit 10

    # 测基线 (裸 LLM)
    python3 evaluate_adversarial.py baseline
    python3 evaluate_adversarial.py baseline --model qwen-turbo

输出:
    Agent_对抗评测结果.json   / 基线_对抗评测结果.json
    Agent_对抗评测报告.txt    / 基线_对抗评测报告.txt
"""

import json
import time
import argparse
import os
import sys
from collections import defaultdict

# ======================== 配置 ========================
TESTSET_FILE = "对抗测试集.json"
DEFAULT_API_URL = "http://127.0.0.1:8000/detect"
DEFAULT_MODEL = "qwen-plus"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
REQUEST_TIMEOUT = 60
RETRY_LIMIT = 3
RETRY_DELAY = 2
RATE_LIMIT_DELAY = 0.5

LABEL_NORMALIZE = {
    "yes": "rumor", "no": "non_rumor", "unknown": "unknown",
    "rumor": "rumor", "non_rumor": "non_rumor", "non-rumor": "non_rumor",
    "not rumor": "non_rumor", "真实": "non_rumor", "谣言": "rumor",
    "不是谣言": "non_rumor", "未知": "unknown", "是": "rumor", "否": "non_rumor",
}

SYSTEM_PROMPT = (
    "判断以下文本是否为谣言。"
    "你必须严格只输出以下三个选项之一：Yes、No、Unknown。"
    "不要输出任何其他内容。"
)


def compute_metrics(results):
    total = len(results)
    correct = sum(1 for r in results if r["match"])
    accuracy = correct / total if total else 0.0

    labels = sorted(set(r["true_label"] for r in results))
    per_label = {}
    for label in labels:
        subset = [r for r in results if r["true_label"] == label]
        tp = sum(1 for r in subset if r["match"])
        per_label[label] = {"total": len(subset), "correct": tp,
                            "accuracy": tp / len(subset) if subset else 0.0}

    precision_recall = {}
    for label in labels:
        tp = sum(1 for r in results if r["true_label"] == label and r["predicted_label"] == label)
        fp = sum(1 for r in results if r["true_label"] != label and r["predicted_label"] == label)
        fn = sum(1 for r in results if r["true_label"] == label and r["predicted_label"] != label)
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        precision_recall[label] = {"precision": p, "recall": r, "f1": f1}

    confusion = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r["true_label"]][r["predicted_label"]] += 1

    return {
        "total": total, "correct": correct, "accuracy": accuracy,
        "per_label_accuracy": per_label,
        "precision_recall_f1": precision_recall,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "all_labels": labels,
    }


def format_report(metrics, method_name, elapsed):
    lines = []
    lines.append("=" * 60)
    lines.append(f"    对抗扰动抵抗度 · {method_name} 评估报告")
    lines.append("=" * 60)
    lines.append(f"  方法:              {method_name}")
    lines.append(f"  测试样本数:        {metrics['total']}")
    lines.append(f"  正确预测数:        {metrics['correct']}")
    lines.append(f"  总体准确率:        {metrics['accuracy']:.1%}")
    lines.append(f"  总耗时:            {elapsed:.1f}s")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  分类别准确率:")
    lines.append(f"  {'标签':>12s}  {'样本数':>6s}  {'正确':>4s}  {'准确率':>8s}")
    lines.append("  " + "-" * 40)
    for label, info in sorted(metrics["per_label_accuracy"].items()):
        lines.append(f"  {label:>12s}  {info['total']:>6d}  {info['correct']:>4d}  {info['accuracy']:>8.1%}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  Precision / Recall / F1:")
    lines.append(f"  {'标签':>12s}  {'Precision':>10s}  {'Recall':>8s}  {'F1':>8s}")
    lines.append("  " + "-" * 44)
    for label, info in sorted(metrics["precision_recall_f1"].items()):
        lines.append(f"  {label:>12s}  {info['precision']:>10.3f}  {info['recall']:>8.3f}  {info['f1']:>8.3f}")
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# ======================== Agent 评测 ========================

def eval_agent(args):
    import requests as req

    script_dir = os.path.dirname(os.path.abspath(__file__))
    testset_path = os.path.join(script_dir, TESTSET_FILE)

    if not os.path.exists(testset_path):
        print(f"❌ 对抗测试集不存在: {testset_path}")
        print("   请先运行: python3 build_adversarial_testset.py")
        sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[:args.limit]

    print(f"📋 对抗测试集已加载: {len(test_data)} 条")
    print(f"🌐 Agent 接口: {args.api}")
    print("=" * 50)

    results = []
    errors = []
    t_start = time.time()

    for idx, item in enumerate(test_data):
        text = item["text"]
        true_label = item["true_label"]
        display = text[:40] + "..." if len(text) > 40 else text

        try:
            resp = req.post(args.api, json={"text": text}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            rj = resp.json()

            conclusion = (rj.get("conclusion") or rj.get("result") or rj.get("label")
                          or rj.get("output") or rj.get("prediction") or "")
            predicted = LABEL_NORMALIZE.get(conclusion.strip().lower(), conclusion.strip().lower())

            match = predicted == true_label
            results.append({"index": idx, "text": text, "original_text": item.get("original_text", ""),
                            "true_label": true_label, "predicted_label": predicted, "match": match,
                            "perturbation_log": item.get("perturbation_log", {})})

            status = "✅" if match else "❌"
            print(f"  [{idx+1:3d}/{len(test_data)}] {status} 真实={true_label:10s} 预测={predicted:10s}  {display}")

        except Exception as e:
            print(f"  [{idx+1:3d}/{len(test_data)}] 🔴 {e}")
            errors.append({"index": idx, "error": str(e)})

    elapsed = time.time() - t_start

    if not results:
        print("❌ 无有效结果"); sys.exit(1)

    metrics = compute_metrics(results)
    report = format_report(metrics, "Agent 智能体（对抗数据）", elapsed)
    print(report)

    report_path = os.path.join(script_dir, "Agent_对抗评测报告.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    detail_path = os.path.join(script_dir, "Agent_对抗评测结果.json")
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "results": results, "errors": errors},
                  f, ensure_ascii=False, indent=2, default=str)

    print(f"📄 报告: {report_path}")
    print(f"📄 详情: {detail_path}")


# ======================== 基线评测 ========================

def eval_baseline(args):
    try:
        from openai import OpenAI
    except ImportError:
        print("❌ 缺少 openai 库: pip install openai"); sys.exit(1)

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY"); sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=QWEN_BASE_URL)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    testset_path = os.path.join(script_dir, TESTSET_FILE)

    if not os.path.exists(testset_path):
        print(f"❌ 对抗测试集不存在，请先运行 build_adversarial_testset.py"); sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[:args.limit]

    print(f"📋 对抗测试集已加载: {len(test_data)} 条")
    print(f"🤖 基线模型: {args.model}")
    print("=" * 50)

    results = []
    errors = []
    t_start = time.time()

    for idx, item in enumerate(test_data):
        text = item["text"]
        true_label = item["true_label"]
        display = text[:40] + "..." if len(text) > 40 else text

        raw_output = None
        for attempt in range(1, RETRY_LIMIT + 1):
            try:
                resp = client.chat.completions.create(
                    model=args.model,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": text}],
                    temperature=0, max_tokens=10)
                raw_output = resp.choices[0].message.content.strip()
                break
            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    time.sleep(RETRY_DELAY * attempt)
                elif attempt == RETRY_LIMIT:
                    errors.append({"index": idx, "error": str(e)})
                else:
                    time.sleep(RETRY_DELAY)

        if raw_output is None:
            continue

        cleaned = raw_output.strip().strip("'\".,。，").lower()
        predicted = LABEL_NORMALIZE.get(cleaned, cleaned)
        if predicted not in ("rumor", "non_rumor", "unknown"):
            for kw, lb in [("yes", "rumor"), ("no", "non_rumor"), ("unknown", "unknown")]:
                if kw in cleaned:
                    predicted = lb; break

        match = predicted == true_label
        results.append({"index": idx, "text": text, "original_text": item.get("original_text", ""),
                        "true_label": true_label, "raw_output": raw_output,
                        "predicted_label": predicted, "match": match,
                        "perturbation_log": item.get("perturbation_log", {})})

        status = "✅" if match else "❌"
        print(f"  [{idx+1:3d}/{len(test_data)}] {status} 真实={true_label:10s} 预测={predicted:10s}  {display}")
        time.sleep(RATE_LIMIT_DELAY)

    elapsed = time.time() - t_start

    if not results:
        print("❌ 无有效结果"); sys.exit(1)

    metrics = compute_metrics(results)
    report = format_report(metrics, f"裸 LLM {args.model}（对抗数据）", elapsed)
    print(report)

    report_path = os.path.join(script_dir, "基线_对抗评测报告.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")

    detail_path = os.path.join(script_dir, "基线_对抗评测结果.json")
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump({"config": {"model": args.model}, "metrics": metrics,
                   "results": results, "errors": errors},
                  f, ensure_ascii=False, indent=2, default=str)

    print(f"📄 报告: {report_path}")
    print(f"📄 详情: {detail_path}")


def main():
    parser = argparse.ArgumentParser(description="对抗扰动抵抗度评测")
    subparsers = parser.add_subparsers(dest="target")

    agent_p = subparsers.add_parser("agent", help="评测 Agent")
    agent_p.add_argument("--api", default=DEFAULT_API_URL)
    agent_p.add_argument("--limit", type=int, default=0)

    base_p = subparsers.add_parser("baseline", help="评测基线 LLM")
    base_p.add_argument("--model", default=DEFAULT_MODEL)
    base_p.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()

    if args.target == "agent":
        eval_agent(args)
    elif args.target == "baseline":
        eval_baseline(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
