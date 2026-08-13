"""
端到端决断延迟 —— 核心基准测试脚本

对延迟测试集中的每条文本，精确测量从发送请求到收到完整响应的
端到端耗时，统计均值、中位数、P90/P95/P99 百分位、吞吐率，
并按文本长度分桶分析延迟分布。

支持评测 Agent 和基线 LLM 两个目标。

用法:
    # 评测 Agent
    python3 benchmark_latency.py --target agent --api http://127.0.0.1:8000/detect

    # 评测基线 LLM
    export DASHSCOPE_API_KEY="sk-xxxxxxxx"
    python3 benchmark_latency.py --target baseline

    # 多轮预热 + 多轮正式测试（减少波动）
    python3 benchmark_latency.py --target agent --warmup 5 --rounds 3

    # 先测 5 条
    python3 benchmark_latency.py --target agent --limit 5

输出:
    Agent_延迟测试结果.json   / Agent_延迟测试报告.txt
    基线_延迟测试结果.json    / 基线_延迟测试报告.txt
"""

import json
import time
import argparse
import os
import sys
import statistics
from collections import defaultdict

try:
    import requests
except ImportError:
    requests = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ======================== 配置 ========================
DEFAULT_API_URL = "http://127.0.0.1:8000/detect"
DEFAULT_MODEL = "qwen-plus"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
REQUEST_TIMEOUT = 120
RETRY_LIMIT = 2
DEFAULT_WARMUP = 3
DEFAULT_ROUNDS = 1

TESTSET_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "延迟测试集.json"
)

SYSTEM_PROMPT = (
    "判断以下文本是否为谣言。"
    "你必须严格只输出以下三个选项之一：Yes、No、Unknown。"
    "不要输出任何其他内容。"
)

LABEL_NORMALIZE = {
    "yes": "rumor", "no": "non_rumor", "unknown": "unknown",
    "rumor": "rumor", "non_rumor": "non_rumor", "non-rumor": "non_rumor",
    "not rumor": "non_rumor", "真实": "non_rumor", "谣言": "rumor",
    "不是谣言": "non_rumor", "未知": "unknown", "是": "rumor", "否": "non_rumor",
}


# ======================== Agent 调用 ========================

def call_agent(text: str, api_url: str) -> dict:
    if requests is None:
        print("❌ 缺少 requests 库: pip install requests")
        sys.exit(1)
    t0 = time.perf_counter()
    resp = requests.post(api_url, json={"text": text}, timeout=REQUEST_TIMEOUT)
    t1 = time.perf_counter()
    resp.raise_for_status()
    return {"latency_s": t1 - t0, "response": resp.json()}


# ======================== 基线 LLM 调用 ========================

def init_qwen_client():
    if OpenAI is None:
        print("❌ 缺少 openai 库: pip install openai")
        sys.exit(1)
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY 环境变量")
        sys.exit(1)
    return OpenAI(api_key=api_key, base_url=QWEN_BASE_URL)


def call_baseline(client, text: str, model: str) -> dict:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        max_tokens=10,
    )
    t1 = time.perf_counter()
    raw = resp.choices[0].message.content.strip()
    return {"latency_s": t1 - t0, "raw_output": raw}


# ======================== 统计工具 ========================

def percentile(data: list[float], p: float) -> float:
    """计算第 p 百分位数 (0~100)"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def compute_latency_stats(latencies: list[float]) -> dict:
    if not latencies:
        return {}
    return {
        "count": len(latencies),
        "mean_s": statistics.mean(latencies),
        "median_s": statistics.median(latencies),
        "stdev_s": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
        "min_s": min(latencies),
        "max_s": max(latencies),
        "p90_s": percentile(latencies, 90),
        "p95_s": percentile(latencies, 95),
        "p99_s": percentile(latencies, 99),
        "total_s": sum(latencies),
        "throughput_qps": len(latencies) / sum(latencies) if sum(latencies) > 0 else 0.0,
    }


def format_latency_report(overall: dict, by_bucket: dict, by_lang: dict,
                          method_name: str, rounds: int) -> str:
    lines = []
    lines.append("=" * 65)
    lines.append(f"    端到端决断延迟 基准测试报告 —— {method_name}")
    lines.append("=" * 65)
    lines.append(f"  方法:          {method_name}")
    lines.append(f"  测试轮次:      {rounds}")
    lines.append(f"  总请求数:      {overall['count']}")
    lines.append("")
    lines.append("  ★ 核心延迟指标:")
    lines.append(f"    平均延迟:    {overall['mean_s']:.3f}s ({overall['mean_s']*1000:.0f}ms)")
    lines.append(f"    中位数 P50:  {overall['median_s']:.3f}s ({overall['median_s']*1000:.0f}ms)")
    lines.append(f"    P90:         {overall['p90_s']:.3f}s ({overall['p90_s']*1000:.0f}ms)")
    lines.append(f"    P95:         {overall['p95_s']:.3f}s ({overall['p95_s']*1000:.0f}ms)")
    lines.append(f"    P99:         {overall['p99_s']:.3f}s ({overall['p99_s']*1000:.0f}ms)")
    lines.append(f"    最快:        {overall['min_s']:.3f}s")
    lines.append(f"    最慢:        {overall['max_s']:.3f}s")
    lines.append(f"    标准差:      {overall['stdev_s']:.3f}s")
    lines.append(f"    吞吐率:      {overall['throughput_qps']:.2f} req/s")
    lines.append("")

    if by_bucket:
        lines.append("-" * 65)
        lines.append("  按文本长度分桶:")
        lines.append(f"  {'分桶':>8s}  {'样本':>4s}  {'平均(s)':>8s}  {'P50(s)':>7s}  {'P90(s)':>7s}  {'P95(s)':>7s}")
        lines.append("  " + "-" * 52)
        for bucket_name, stats in sorted(by_bucket.items()):
            if not stats:
                continue
            lines.append(
                f"  {bucket_name:>8s}  {stats['count']:>4d}  "
                f"{stats['mean_s']:>8.3f}  {stats['median_s']:>7.3f}  "
                f"{stats['p90_s']:>7.3f}  {stats['p95_s']:>7.3f}"
            )
        lines.append("")

    if by_lang:
        lines.append("-" * 65)
        lines.append("  按语言:")
        lines.append(f"  {'语言':>6s}  {'样本':>4s}  {'平均(s)':>8s}  {'P50(s)':>7s}  {'P90(s)':>7s}")
        lines.append("  " + "-" * 40)
        for lang, stats in sorted(by_lang.items()):
            if not stats:
                continue
            lines.append(
                f"  {lang:>6s}  {stats['count']:>4d}  "
                f"{stats['mean_s']:>8.3f}  {stats['median_s']:>7.3f}  "
                f"{stats['p90_s']:>7.3f}"
            )
        lines.append("")

    lines.append("-" * 65)
    lines.append("  延迟分布直方图 (每个 █ 代表 1 个请求):")
    if overall.get("count"):
        all_latencies = []
        bins = [
            ("< 1s", 0, 1),
            ("1~3s", 1, 3),
            ("3~5s", 3, 5),
            ("5~10s", 5, 10),
            ("10~20s", 10, 20),
            ("> 20s", 20, 99999),
        ]
        lines.append(f"  (需配合 JSON 结果中的 latency_s 字段绘制)")
    lines.append("")
    lines.append("=" * 65)
    return "\n".join(lines)


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(description="端到端决断延迟基准测试")
    parser.add_argument("--target", choices=["agent", "baseline"], required=True)
    parser.add_argument("--api", default=DEFAULT_API_URL, help="Agent 接口地址")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"基线模型 (默认 {DEFAULT_MODEL})")
    parser.add_argument("--testset", default=TESTSET_FILE, help="测试集 JSON")
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 条 (0=全部)")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                        help=f"预热请求数 (默认 {DEFAULT_WARMUP})")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help=f"正式测试轮次 (默认 {DEFAULT_ROUNDS}，多轮取平均)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    testset_path = os.path.abspath(args.testset)

    if not os.path.exists(testset_path):
        print(f"❌ 测试集不存在: {testset_path}")
        print("   请先运行: python3 build_latency_testset.py")
        sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[:args.limit]

    is_agent = args.target == "agent"
    method_name = "Agent 智能体（完整管线）" if is_agent else f"基线 LLM ({args.model})"
    prefix = "Agent" if is_agent else "基线"

    client = None
    if not is_agent:
        client = init_qwen_client()

    print(f"📋 测试集: {len(test_data)} 条")
    print(f"🎯 目标: {method_name}")
    print(f"🔥 预热: {args.warmup} 条  |  正式轮次: {args.rounds}")
    print("=" * 55)

    # ---- 预热 ----
    if args.warmup > 0:
        warmup_items = test_data[:min(args.warmup, len(test_data))]
        print(f"🔥 预热中 ({len(warmup_items)} 条)...")
        for item in warmup_items:
            try:
                if is_agent:
                    call_agent(item["text"], args.api)
                else:
                    call_baseline(client, item["text"], args.model)
            except Exception:
                pass
        print("   预热完成\n")

    # ---- 正式测试 ----
    all_results = []

    for round_idx in range(1, args.rounds + 1):
        if args.rounds > 1:
            print(f"━━━ 第 {round_idx}/{args.rounds} 轮 ━━━")

        for idx, item in enumerate(test_data):
            text = item["text"]
            display = text[:35] + ("..." if len(text) > 35 else "")

            latency = None
            error = None

            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    if is_agent:
                        result = call_agent(text, args.api)
                        latency = result["latency_s"]
                    else:
                        result = call_baseline(client, text, args.model)
                        latency = result["latency_s"]
                    break
                except Exception as e:
                    if attempt == RETRY_LIMIT:
                        error = str(e)
                        print(f"  [{idx+1:3d}/{len(test_data)}] 🔴 失败: {e}")
                    else:
                        time.sleep(1)

            if latency is not None:
                record = {
                    "index": item.get("index", idx),
                    "round": round_idx,
                    "text": text,
                    "char_length": len(text),
                    "length_bucket": item.get("length_bucket", "未知"),
                    "language": item.get("language", "unknown"),
                    "true_label": item.get("true_label", ""),
                    "latency_s": round(latency, 4),
                    "latency_ms": round(latency * 1000, 1),
                }
                all_results.append(record)

                speed_icon = "⚡" if latency < 3 else ("🟡" if latency < 10 else "🐢")
                print(
                    f"  [{idx+1:3d}/{len(test_data)}] {speed_icon} "
                    f"{latency:.3f}s ({latency*1000:.0f}ms)  "
                    f"[{item.get('length_bucket', '?')}]  {display}"
                )
            elif error:
                all_results.append({
                    "index": item.get("index", idx),
                    "round": round_idx,
                    "text": text,
                    "error": error,
                    "latency_s": None,
                })

    print(f"\n{'=' * 55}")

    valid = [r for r in all_results if r.get("latency_s") is not None]
    if not valid:
        print("❌ 无有效测量结果")
        sys.exit(1)

    latencies = [r["latency_s"] for r in valid]
    overall = compute_latency_stats(latencies)

    by_bucket = {}
    bucket_groups = defaultdict(list)
    for r in valid:
        bucket_groups[r["length_bucket"]].append(r["latency_s"])
    for bucket_name, lats in bucket_groups.items():
        by_bucket[bucket_name] = compute_latency_stats(lats)

    by_lang = {}
    lang_groups = defaultdict(list)
    for r in valid:
        lang_groups[r["language"]].append(r["latency_s"])
    for lang, lats in lang_groups.items():
        by_lang[lang] = compute_latency_stats(lats)

    report = format_latency_report(overall, by_bucket, by_lang, method_name, args.rounds)
    print(report)

    report_path = os.path.join(script_dir, f"{prefix}_延迟测试报告.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_path = os.path.join(script_dir, f"{prefix}_延迟测试结果.json")
    detail_output = {
        "config": {
            "target": args.target,
            "method": method_name,
            "rounds": args.rounds,
            "warmup": args.warmup,
        },
        "overall_stats": overall,
        "by_length_bucket": by_bucket,
        "by_language": by_lang,
        "results": all_results,
    }
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 逐条结果已保存: {detail_path}")

    errors = [r for r in all_results if r.get("latency_s") is None]
    if errors:
        print(f"\n⚠️  共 {len(errors)} 条请求失败")


if __name__ == "__main__":
    main()
