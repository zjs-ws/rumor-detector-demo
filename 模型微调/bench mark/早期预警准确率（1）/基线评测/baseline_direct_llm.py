"""
基线 1：裸 LLM 直接 Prompting 对比评测

用同一个底座模型 (Qwen)，但绕过 Agent 的所有增强能力（推理链、知识检索、
多工具协同），仅用一条极简 Prompt 让模型做一次性谣言判断。
与 Agent 跑同一份测试集，对比准确率差异，证明 Agent 架构的增益。

用法:
    export DASHSCOPE_API_KEY="sk-xxxxxxxx"
    python3 baseline_direct_llm.py                       # 全部 200 条
    python3 baseline_direct_llm.py --limit 10            # 先测 10 条
    python3 baseline_direct_llm.py --model qwen-turbo    # 换模型

输出:
    基线1_裸LLM评估报告.txt   —— 完整评估报告
    基线1_裸LLM逐条结果.json  —— 每条数据的预测详情
"""

import json
import time
import argparse
import os
import sys
from collections import defaultdict

try:
    from openai import OpenAI
except ImportError:
    print("❌ 缺少 openai 库，请先执行: pip install openai")
    sys.exit(1)

# ======================== 配置 ========================
DEFAULT_MODEL = "qwen-plus"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
TESTSET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "早期预警测试集.json")
OUTPUT_REPORT = "基线1_裸LLM评估报告.txt"
OUTPUT_DETAIL = "基线1_裸LLM逐条结果.json"
REQUEST_TIMEOUT = 60
RETRY_LIMIT = 3
RETRY_DELAY = 2
RATE_LIMIT_DELAY = 0.5

SYSTEM_PROMPT = (
    "判断以下文本是否为谣言。"
    "你必须严格只输出以下三个选项之一：Yes、No、Unknown。"
    "不要输出任何其他内容。"
)

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
    "不是谣言": "non_rumor",
    "未知": "unknown",
    "是": "rumor",
    "否": "non_rumor",
}


def init_client() -> OpenAI:
    """初始化 Qwen API 客户端"""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY 环境变量")
        print('   请先执行: export DASHSCOPE_API_KEY="sk-xxxxxxxx"')
        print("   API Key 从 https://dashscope.console.aliyun.com/ 获取")
        sys.exit(1)
    return OpenAI(api_key=api_key, base_url=QWEN_BASE_URL)


def baseline_predict(client: OpenAI, text: str, model: str) -> str:
    """裸 LLM 一次性判断，无 Agent 增强"""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        max_tokens=10,
    )
    return resp.choices[0].message.content.strip()


def normalize_prediction(raw_output: str) -> str:
    """将 LLM 原始输出归一化为标准标签"""
    cleaned = raw_output.strip().strip("'\".,。，").lower()

    exact = LABEL_NORMALIZE.get(cleaned)
    if exact:
        return exact

    for keyword, label in [
        ("yes", "rumor"), ("no", "non_rumor"), ("unknown", "unknown"),
        ("谣言", "rumor"), ("不是", "non_rumor"), ("真实", "non_rumor"),
        ("未知", "unknown"), ("无法判断", "unknown"),
    ]:
        if keyword in cleaned:
            return label

    return cleaned


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


def format_report(metrics: dict, elapsed: float, model: str) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("    基线 1：裸 LLM 直接 Prompting 评估报告")
    lines.append("=" * 60)
    lines.append(f"  模型:              {model}")
    lines.append(f"  方法:              直接 Prompting（无 Agent 架构）")
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
    parser = argparse.ArgumentParser(description="基线1：裸 LLM 直接 Prompting 对比评测")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Qwen 模型名 (默认 {DEFAULT_MODEL})")
    parser.add_argument("--testset", default=TESTSET_FILE, help="测试集 JSON 文件路径")
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 条 (0=全部)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    testset_path = os.path.abspath(args.testset)

    if not os.path.exists(testset_path):
        print(f"❌ 测试集文件不存在: {testset_path}")
        print("   请先在上级目录运行: python3 build_early_warning_testset.py")
        sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[: args.limit]

    client = init_client()

    print(f"📋 测试集已加载: {len(test_data)} 条记录")
    print(f"🤖 模型: {args.model}")
    print(f"📌 方法: 直接 Prompting（无 Agent 架构）")
    print("=" * 50)

    results = []
    errors = []
    t_start = time.time()

    for idx, item in enumerate(test_data):
        text = item["text"]
        true_label = item["true_label"]
        display_text = text[:40] + ("..." if len(text) > 40 else "")

        raw_output = None
        for attempt in range(1, RETRY_LIMIT + 1):
            try:
                raw_output = baseline_predict(client, text, args.model)
                break
            except Exception as e:
                err_str = str(e)
                if "rate" in err_str.lower() or "429" in err_str:
                    wait = RETRY_DELAY * attempt
                    print(f"  [{idx + 1:3d}/{len(test_data)}] ⏳ 限流，等待 {wait}s 后重试 ({attempt}/{RETRY_LIMIT})")
                    time.sleep(wait)
                elif attempt == RETRY_LIMIT:
                    print(f"  [{idx + 1:3d}/{len(test_data)}] 🔴 失败: {e}")
                    errors.append({"index": idx, "text": text, "error": err_str})
                else:
                    time.sleep(RETRY_DELAY)

        if raw_output is None:
            continue

        predicted_label = normalize_prediction(raw_output)
        match = predicted_label == true_label

        record = {
            "index": idx,
            "text": text,
            "true_label": true_label,
            "raw_output": raw_output,
            "predicted_label": predicted_label,
            "match": match,
        }
        results.append(record)

        status = "✅" if match else "❌"
        print(
            f"  [{idx + 1:3d}/{len(test_data)}] {status} "
            f"真实={true_label:10s} 预测={predicted_label:10s} "
            f'(原始输出="{raw_output}")  {display_text}'
        )

        time.sleep(RATE_LIMIT_DELAY)

    elapsed = time.time() - t_start
    print(f"\n{'=' * 50}")

    if not results:
        print("❌ 无有效结果，请检查 API Key 和网络连接")
        sys.exit(1)

    metrics = compute_metrics(results)
    report = format_report(metrics, elapsed, args.model)
    print(report)

    report_path = os.path.join(script_dir, OUTPUT_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_path = os.path.join(script_dir, OUTPUT_DETAIL)
    detail_output = {
        "config": {
            "model": args.model,
            "method": "Direct Prompting (no Agent)",
            "system_prompt": SYSTEM_PROMPT,
        },
        "metrics_summary": metrics,
        "results": results,
        "errors": errors,
    }
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 逐条结果已保存: {detail_path}")

    if errors:
        print(f"\n⚠️  共 {len(errors)} 条请求失败，详见逐条结果文件")


if __name__ == "__main__":
    main()
