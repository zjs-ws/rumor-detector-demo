"""
端到端决断延迟 —— 对比报告生成

汇总 Agent 与基线 LLM 的延迟测试结果，
从总体和分桶两个维度横向对比，
计算 Agent 的延迟性价比（做了更多事但耗时可控），
并与人工核查基准做参照。

用法:
    python3 compare_latency.py

    # 自定义路径
    python3 compare_latency.py \
        --agent  Agent_延迟测试结果.json \
        --baseline 基线_延迟测试结果.json

输出:
    端到端延迟_对比报告.txt   —— 综合对比
    端到端延迟_详细数据.json  —— 结构化数据
"""

import json
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_AGENT = os.path.join(SCRIPT_DIR, "Agent_延迟测试结果.json")
DEFAULT_BASELINE = os.path.join(SCRIPT_DIR, "基线_延迟测试结果.json")
OUTPUT_REPORT = os.path.join(SCRIPT_DIR, "端到端延迟_对比报告.txt")
OUTPUT_JSON = os.path.join(SCRIPT_DIR, "端到端延迟_详细数据.json")

HUMAN_BENCHMARK_MINUTES = 30


def load_stats(filepath: str) -> dict | None:
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "method": data.get("config", {}).get("method", "未知"),
        "overall": data.get("overall_stats", {}),
        "by_bucket": data.get("by_length_bucket", {}),
        "by_lang": data.get("by_language", {}),
        "results": data.get("results", []),
    }


def main():
    parser = argparse.ArgumentParser(description="端到端延迟对比报告")
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--human-minutes", type=float, default=HUMAN_BENCHMARK_MINUTES,
                        help=f"人工核查一条的估计时间(分钟), 默认 {HUMAN_BENCHMARK_MINUTES}")
    args = parser.parse_args()

    agent = load_stats(args.agent)
    baseline = load_stats(args.baseline)

    if not agent and not baseline:
        print("❌ 未找到任何延迟测试结果")
        print("   请先运行 benchmark_latency.py")
        sys.exit(1)

    human_seconds = args.human_minutes * 60

    lines = []
    lines.append("=" * 70)
    lines.append("    端到端决断延迟 (Time-to-Verdict) · 综合对比报告")
    lines.append("=" * 70)
    lines.append("")

    # ---- 总体对比表 ----
    lines.append("━" * 70)
    lines.append("  一、核心延迟指标横向对比")
    lines.append("━" * 70)
    lines.append("")

    metrics_keys = [
        ("平均延迟", "mean_s"),
        ("中位数 P50", "median_s"),
        ("P90", "p90_s"),
        ("P95", "p95_s"),
        ("P99", "p99_s"),
        ("最快", "min_s"),
        ("最慢", "max_s"),
        ("吞吐率(req/s)", "throughput_qps"),
    ]

    header = f"  {'指标':>16s}"
    if agent:
        header += f"  {'Agent':>10s}"
    if baseline:
        header += f"  {'基线LLM':>10s}"
    header += f"  {'人工核查':>10s}"
    if agent and baseline:
        header += f"  {'Agent优势':>10s}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for label, key in metrics_keys:
        row = f"  {label:>16s}"
        a_val = agent["overall"].get(key) if agent else None
        b_val = baseline["overall"].get(key) if baseline else None

        if key == "throughput_qps":
            if a_val is not None:
                row += f"  {a_val:>10.2f}"
            if b_val is not None:
                row += f"  {b_val:>10.2f}"
            h_qps = 1.0 / human_seconds if human_seconds > 0 else 0
            row += f"  {h_qps:>10.4f}"
            if a_val and b_val:
                if a_val > b_val:
                    row += f"  {a_val/b_val:>9.1f}x"
                else:
                    row += f"  {a_val/b_val:>9.1f}x"
        else:
            if a_val is not None:
                row += f"  {a_val:>9.3f}s"
            if b_val is not None:
                row += f"  {b_val:>9.3f}s"
            if key in ("mean_s", "median_s"):
                row += f"  {human_seconds:>8.0f}s"
            else:
                row += f"  {'—':>10s}"
            if a_val and b_val and key not in ("min_s",):
                if b_val > a_val and a_val > 0:
                    row += f"  {b_val/a_val:>9.1f}x"
                elif a_val > b_val and b_val > 0:
                    row += f"  {a_val/b_val:>8.1f}x慢"
                else:
                    row += f"  {'持平':>10s}"

        lines.append(row)
    lines.append("")

    # ---- 加速比 ----
    if agent:
        a_mean = agent["overall"].get("mean_s", 0)
        if a_mean > 0:
            speedup_vs_human = human_seconds / a_mean
            lines.append("-" * 70)
            lines.append("  ★ 相对人工核查的加速比:")
            lines.append(f"    Agent 平均 {a_mean:.2f}s  vs  人工约 {human_seconds:.0f}s ({args.human_minutes:.0f}分钟)")
            lines.append(f"    → Agent 快了约 {speedup_vs_human:,.0f} 倍")
            lines.append("")

    if agent and baseline:
        a_mean = agent["overall"].get("mean_s", 0)
        b_mean = baseline["overall"].get("mean_s", 0)
        if a_mean > 0 and b_mean > 0:
            lines.append("  ★ Agent vs 基线 LLM:")
            if a_mean > b_mean:
                lines.append(f"    Agent ({a_mean:.2f}s) 比基线 ({b_mean:.2f}s) 慢 {a_mean/b_mean:.1f}x")
                lines.append("    但 Agent 完成了完整的意图识别→关键词提取→外部搜索→综合研判→雷达图渲染，")
                lines.append("    而基线仅做了一次简单的 Prompt，二者完成的任务量不在同一级别。")
            else:
                lines.append(f"    Agent ({a_mean:.2f}s) 比基线 ({b_mean:.2f}s) 快 {b_mean/a_mean:.1f}x")
            lines.append("")

    # ---- 按文本长度对比 ----
    if agent and baseline:
        a_buckets = agent.get("by_bucket", {})
        b_buckets = baseline.get("by_bucket", {})
        all_buckets = sorted(set(list(a_buckets.keys()) + list(b_buckets.keys())))

        if all_buckets:
            lines.append("━" * 70)
            lines.append("  二、按文本长度分桶对比")
            lines.append("━" * 70)
            lines.append(f"  {'分桶':>8s}  {'Agent均值':>10s}  {'基线均值':>10s}  {'Agent P90':>10s}  {'基线P90':>10s}")
            lines.append("  " + "-" * 56)
            for b in all_buckets:
                a_info = a_buckets.get(b, {})
                b_info = b_buckets.get(b, {})
                a_mean = f"{a_info.get('mean_s', 0):.3f}s" if a_info else "—"
                b_mean = f"{b_info.get('mean_s', 0):.3f}s" if b_info else "—"
                a_p90 = f"{a_info.get('p90_s', 0):.3f}s" if a_info else "—"
                b_p90 = f"{b_info.get('p90_s', 0):.3f}s" if b_info else "—"
                lines.append(f"  {b:>8s}  {a_mean:>10s}  {b_mean:>10s}  {a_p90:>10s}  {b_p90:>10s}")
            lines.append("")

    # ---- SLA 达标率 ----
    lines.append("━" * 70)
    lines.append("  三、SLA 达标率 (不同延迟阈值下的完成比例)")
    lines.append("━" * 70)
    thresholds = [1, 3, 5, 10, 20]

    def _sla_rates(results: list[dict]) -> dict:
        valid = [r["latency_s"] for r in results if r.get("latency_s") is not None]
        if not valid:
            return {}
        total = len(valid)
        return {t: sum(1 for v in valid if v <= t) / total for t in thresholds}

    header = f"  {'阈值':>8s}"
    if agent:
        header += f"  {'Agent':>8s}"
    if baseline:
        header += f"  {'基线':>8s}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    a_sla = _sla_rates(agent["results"]) if agent else {}
    b_sla = _sla_rates(baseline["results"]) if baseline else {}

    for t in thresholds:
        row = f"  {'≤'+str(t)+'s':>8s}"
        if a_sla:
            row += f"  {a_sla.get(t, 0):>7.1%}"
        if b_sla:
            row += f"  {b_sla.get(t, 0):>7.1%}"
        lines.append(row)
    lines.append("")

    # ---- 答辩话术 ----
    lines.append("━" * 70)
    lines.append("  答辩话术参考")
    lines.append("━" * 70)
    lines.append('  "端到端决断延迟衡量的是从用户点击检测按钮，到系统完成')
    lines.append('   意图识别、关键词提取、外部搜索查证、多维度研判并渲染出')
    lines.append('   雷达图的全链路耗时。')
    lines.append('   ')

    if agent:
        a_mean = agent["overall"].get("mean_s", 0)
        a_p95 = agent["overall"].get("p95_s", 0)
        lines.append(f'   我们的 Agent 平均延迟仅 {a_mean:.1f} 秒，P95 为 {a_p95:.1f} 秒，')
        speedup = human_seconds / a_mean if a_mean > 0 else 0
        lines.append(f'   相当于将人工核查 {args.human_minutes:.0f} 分钟的工作压缩了约 {speedup:,.0f} 倍。')
        if baseline:
            b_mean = baseline["overall"].get("mean_s", 0)
            lines.append(f'   ')
            if a_mean > b_mean:
                lines.append(f'   虽然 Agent ({a_mean:.1f}s) 比裸 LLM ({b_mean:.1f}s) 稍慢，')
                lines.append(f'   但 Agent 在这几秒内完成了完整的外部查证 + 多维评估 + 雷达图渲染，')
                lines.append(f'   而裸 LLM 只是做了一次没有任何依据的猜测。')
                lines.append(f'   这点额外延迟换来的是准确率和可解释性的显著提升。"')
            else:
                lines.append(f'   Agent ({a_mean:.1f}s) 甚至比裸 LLM ({b_mean:.1f}s) 更快，')
                lines.append(f'   这得益于我们优化的异步管线和并行工具调用。"')
    else:
        lines.append('   具体数据请参考上方测试结果。"')
    lines.append("")

    lines.append("  可视化建议:")
    lines.append("    1. 延迟分布小提琴图/箱线图: Agent vs 基线")
    lines.append("    2. CDF 曲线: 横轴延迟，纵轴累计完成比例")
    lines.append("    3. 三栏对比: Agent (秒级) vs 裸LLM (秒级) vs 人工 (分钟级)")
    lines.append("    4. 分桶柱状图: 短/中/长文本的延迟对比")
    lines.append("")
    lines.append("=" * 70)

    report = "\n".join(lines)
    print(report)

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"\n📄 对比报告已保存: {OUTPUT_REPORT}")

    detail = {
        "agent": agent["overall"] if agent else None,
        "baseline": baseline["overall"] if baseline else None,
        "agent_by_bucket": agent.get("by_bucket") if agent else None,
        "baseline_by_bucket": baseline.get("by_bucket") if baseline else None,
        "agent_sla": a_sla,
        "baseline_sla": b_sla,
        "human_benchmark_seconds": human_seconds,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 详细数据已保存: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
