"""
对抗扰动抵抗度 —— 第三步：计算净/脏准确率跌幅对比

读取指标一的"纯净数据"评测结果 和 本指标的"脏数据"评测结果，
计算两者的准确率跌幅 (Degradation)。

核心指标:
    准确率跌幅 = 纯净准确率 - 对抗准确率
    跌幅越小 = 抗干扰能力越强

用法:
    python3 compare_degradation.py

    # 指定文件路径
    python3 compare_degradation.py \
        --agent-clean   ../早期预警准确率（1）/Agent评测/早期预警逐条结果.json \
        --agent-adv     Agent_对抗评测结果.json \
        --baseline-clean ../早期预警准确率（1）/基线评测/基线1_裸LLM逐条结果.json \
        --baseline-adv  基线_对抗评测结果.json

输出:
    对抗扰动抵抗度_对比报告.txt
"""

import json
import argparse
import os
import sys

# ======================== 配置 ========================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.join(SCRIPT_DIR, "..")

DEFAULT_PATHS = {
    "agent_clean": os.path.join(PARENT_DIR, "早期预警准确率（1）", "Agent评测", "早期预警逐条结果.json"),
    "agent_adv": os.path.join(SCRIPT_DIR, "Agent_对抗评测结果.json"),
    "baseline_clean": os.path.join(PARENT_DIR, "早期预警准确率（1）", "基线评测", "基线1_裸LLM逐条结果.json"),
    "baseline_adv": os.path.join(SCRIPT_DIR, "基线_对抗评测结果.json"),
}

OUTPUT_REPORT = "对抗扰动抵抗度_对比报告.txt"


def load_accuracy(filepath: str) -> float | None:
    """从评测结果 JSON 中提取准确率"""
    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "metrics" in data:
            return data["metrics"].get("accuracy")
        if "metrics_summary" in data:
            return data["metrics_summary"].get("accuracy")
        if "accuracy" in data:
            return data["accuracy"]
        if "results" in data:
            results = data["results"]
            if results:
                correct = sum(1 for r in results if r.get("match"))
                return correct / len(results)
    elif isinstance(data, list):
        if data:
            correct = sum(1 for r in data if r.get("match"))
            return correct / len(data)

    return None


def main():
    parser = argparse.ArgumentParser(description="净/脏准确率跌幅对比")
    parser.add_argument("--agent-clean", default=DEFAULT_PATHS["agent_clean"])
    parser.add_argument("--agent-adv", default=DEFAULT_PATHS["agent_adv"])
    parser.add_argument("--baseline-clean", default=DEFAULT_PATHS["baseline_clean"])
    parser.add_argument("--baseline-adv", default=DEFAULT_PATHS["baseline_adv"])
    args = parser.parse_args()

    agent_clean_acc = load_accuracy(os.path.abspath(args.agent_clean))
    agent_adv_acc = load_accuracy(os.path.abspath(args.agent_adv))
    baseline_clean_acc = load_accuracy(os.path.abspath(args.baseline_clean))
    baseline_adv_acc = load_accuracy(os.path.abspath(args.baseline_adv))

    lines = []
    lines.append("=" * 60)
    lines.append("    对抗扰动抵抗度 (Adversarial Resilience) 对比报告")
    lines.append("=" * 60)
    lines.append("")

    lines.append("  ┌──────────────────────────────────────────────────┐")
    lines.append(f"  │ {'方法':>12s}  {'纯净数据':>10s}  {'对抗数据':>10s}  {'跌幅':>8s}     │")
    lines.append("  ├──────────────────────────────────────────────────┤")

    def fmt_row(name, clean, adv):
        if clean is not None and adv is not None:
            drop = clean - adv
            drop_str = f"{drop:>+7.1%}"
            return f"  │ {name:>10s}  {clean:>10.1%}  {adv:>10.1%}  {drop_str:>8s}     │"
        elif clean is not None:
            return f"  │ {name:>10s}  {clean:>10.1%}  {'(未测)':>10s}  {'--':>8s}     │"
        elif adv is not None:
            return f"  │ {name:>10s}  {'(未测)':>10s}  {adv:>10.1%}  {'--':>8s}     │"
        else:
            return f"  │ {name:>10s}  {'(未测)':>10s}  {'(未测)':>10s}  {'--':>8s}     │"

    lines.append(fmt_row("Agent", agent_clean_acc, agent_adv_acc))
    lines.append(fmt_row("裸 LLM", baseline_clean_acc, baseline_adv_acc))
    lines.append("  └──────────────────────────────────────────────────┘")
    lines.append("")

    if (agent_clean_acc is not None and agent_adv_acc is not None
            and baseline_clean_acc is not None and baseline_adv_acc is not None):
        agent_drop = agent_clean_acc - agent_adv_acc
        baseline_drop = baseline_clean_acc - baseline_adv_acc

        lines.append("-" * 60)
        lines.append("  关键结论:")
        lines.append(f"    Agent 跌幅:      {agent_drop:>+.1%}")
        lines.append(f"    基线跌幅:        {baseline_drop:>+.1%}")

        if agent_drop < baseline_drop:
            advantage = baseline_drop - agent_drop
            lines.append(f"    Agent 抗干扰优势: {advantage:.1%}")
            lines.append("")
            lines.append(f"    ★ Agent 面对对抗扰动仅跌 {agent_drop:.1%}，")
            lines.append(f"      而基线跌了 {baseline_drop:.1%}，")
            lines.append(f"      Agent 的抗干扰能力优于基线 {advantage:.1%}")
        elif agent_drop > baseline_drop:
            lines.append(f"    ⚠️  基线的跌幅反而更小，请检查数据")
        else:
            lines.append(f"    两者跌幅相近")

        lines.append("")
        lines.append("-" * 60)
        lines.append("  结题报告话术参考:")
        lines.append("")
        lines.append(f'    "在施加谐音替换、字符穿插、视觉混淆等 6 类对抗扰动后，')
        lines.append(f'     Agent 的准确率仅从 {agent_clean_acc:.1%} 下降至 {agent_adv_acc:.1%}')
        lines.append(f'     （跌幅 {agent_drop:.1%}），而裸 LLM 基线从')
        lines.append(f'     {baseline_clean_acc:.1%} 暴跌至 {baseline_adv_acc:.1%}')
        lines.append(f'     （跌幅 {baseline_drop:.1%}）。Agent 的抗干扰能力')
        lines.append(f'     比基线强 {advantage:.1%}，证明其具备对抗扰动文本')
        lines.append(f'     的鲁棒性。"')
    else:
        lines.append("-" * 60)
        lines.append("  ⚠️  部分数据缺失，无法计算完整对比。")
        lines.append("  请确保以下评测均已完成:")
        if agent_clean_acc is None:
            lines.append(f"    ❌ Agent 纯净数据评测 ({args.agent_clean})")
        if agent_adv_acc is None:
            lines.append(f"    ❌ Agent 对抗数据评测 ({args.agent_adv})")
        if baseline_clean_acc is None:
            lines.append(f"    ❌ 基线纯净数据评测 ({args.baseline_clean})")
        if baseline_adv_acc is None:
            lines.append(f"    ❌ 基线对抗数据评测 ({args.baseline_adv})")

    lines.append("")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    report_path = os.path.join(SCRIPT_DIR, OUTPUT_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 对比报告已保存: {report_path}")


if __name__ == "__main__":
    main()
