"""
解释质量与自洽度 —— 量化条件 2：A/B 盲测 (Blind Evaluation)

将 Agent 生成的多维辟谣报告与基线模型的简短解释配对，
随机打乱顺序（抹去来源身份），生成盲测问卷供同学评估。

两种输出模式：
  - 终端交互式：一个人当场做盲测
  - 导出 CSV/JSON：发给多人做问卷

用法:
    # Step 1: 生成盲测问卷
    python3 abtest_blind_eval.py generate \
        --agent agent_results.json \
        --baseline baseline_results.json

    # Step 2a: 终端交互式盲测
    python3 abtest_blind_eval.py evaluate

    # Step 2b: 导出 CSV 问卷
    python3 abtest_blind_eval.py evaluate --export-csv

    # Step 3: 收集结果并统计胜率
    python3 abtest_blind_eval.py stats
    python3 abtest_blind_eval.py stats --import-csv voter1.csv voter2.csv ...

输出:
    盲测问卷.json         —— 配对好的盲测题目
    盲测投票结果.json      —— 投票数据
    盲测胜率报告.txt       —— 统计报告
"""

import json
import random
import argparse
import os
import sys
import csv
from collections import Counter

# ======================== 配置 ========================
QUESTIONNAIRE_FILE = "盲测问卷.json"
VOTES_FILE = "盲测投票结果.json"
STATS_REPORT = "盲测胜率报告.txt"
CSV_EXPORT = "盲测问卷模板.csv"
SAMPLE_SIZE = 30


def build_pairs(agent_results: list, baseline_results: list, sample: int) -> list:
    """将 Agent 和基线结果按文本配对，随机分配 A/B 位置"""
    agent_map = {}
    for item in agent_results:
        text = item.get("text", "")
        reason = item.get("reason", "") or item.get("agent_reason", "")
        if text and reason:
            agent_map[text[:100]] = {"text": text, "reason": reason, "source": "agent"}

    baseline_map = {}
    for item in baseline_results:
        text = item.get("text", "")
        reason = item.get("reason", "") or item.get("raw_output", "") or item.get("agent_reason", "")
        if text and reason:
            baseline_map[text[:100]] = {"text": text, "reason": reason, "source": "baseline"}

    common_keys = set(agent_map.keys()) & set(baseline_map.keys())

    if not common_keys:
        print("⚠️  未找到文本重叠的配对，将按顺序配对")
        agent_list = list(agent_map.values())
        baseline_list = list(baseline_map.values())
        n = min(len(agent_list), len(baseline_list), sample)
        pairs_raw = list(zip(agent_list[:n], baseline_list[:n]))
    else:
        pairs_raw = [(agent_map[k], baseline_map[k]) for k in common_keys]

    random.seed(42)
    if len(pairs_raw) > sample:
        pairs_raw = random.sample(pairs_raw, sample)

    questionnaire = []
    for i, (agent_item, baseline_item) in enumerate(pairs_raw):
        agent_is_a = random.random() > 0.5
        if agent_is_a:
            option_a = {"reason": agent_item["reason"], "hidden_source": "agent"}
            option_b = {"reason": baseline_item["reason"], "hidden_source": "baseline"}
        else:
            option_a = {"reason": baseline_item["reason"], "hidden_source": "baseline"}
            option_b = {"reason": agent_item["reason"], "hidden_source": "agent"}

        questionnaire.append({
            "pair_id": i + 1,
            "original_text": agent_item["text"],
            "option_a": option_a["reason"],
            "option_b": option_b["reason"],
            "_hidden_a_source": option_a["hidden_source"],
            "_hidden_b_source": option_b["hidden_source"],
        })

    return questionnaire


def interactive_evaluate(questionnaire: list, voter_name: str) -> list:
    """交互式盲测"""
    print()
    print("=" * 60)
    print("    辟谣报告质量盲测 (A/B Test)")
    print("=" * 60)
    print()
    print("  规则：阅读原帖和两份辟谣报告 A/B，")
    print("  选择你作为网民更信服的那一份。")
    print("  输入 a 或 b，输入 t 表示两者差不多，输入 q 退出。")
    print()

    votes = []
    total = len(questionnaire)

    for item in questionnaire:
        pid = item["pair_id"]
        print(f"\n{'━' * 60}")
        print(f"  [{pid}/{total}] 原帖:")
        print(f"    {item['original_text'][:150]}{'...' if len(item['original_text']) > 150 else ''}")
        print()
        print(f"  ┌── 报告 A ──")
        for line in item["option_a"].split("\n"):
            print(f"  │ {line}")
        print(f"  └──────────")
        print()
        print(f"  ┌── 报告 B ──")
        for line in item["option_b"].split("\n"):
            print(f"  │ {line}")
        print(f"  └──────────")

        while True:
            choice = input(f"\n  你更信服哪份？[a / b / t(平手) / q(退出)]: ").strip().lower()
            if choice in ("a", "b", "t", "q"):
                break
            print("  ⚠️  请输入 a / b / t / q")

        if choice == "q":
            print(f"\n💾 已保存 {len(votes)} 条投票")
            break

        votes.append({
            "pair_id": pid,
            "voter": voter_name,
            "choice": choice,
        })
        print(f"  ✅ 已投票 ({len(votes)}/{total})")

    return votes


def export_csv_questionnaire(questionnaire: list, output_path: str):
    """导出 CSV 问卷"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "题号", "原帖文本", "报告A", "报告B",
            "你的选择(a=选A/b=选B/t=平手)", "评测人姓名"
        ])
        for item in questionnaire:
            writer.writerow([
                item["pair_id"],
                item["original_text"][:500],
                item["option_a"][:2000],
                item["option_b"][:2000],
                "",
                "",
            ])
    print(f"✅ CSV 问卷已导出: {output_path}")
    print("   发给同学，让他们在'你的选择'列填 a/b/t")


def import_csv_votes(csv_paths: list) -> list:
    """从多个已填写的 CSV 导入投票"""
    all_votes = []
    for csv_path in csv_paths:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                choice = row.get("你的选择(a=选A/b=选B/t=平手)", "").strip().lower()
                voter = row.get("评测人姓名", "").strip() or os.path.basename(csv_path)
                pid = row.get("题号", "").strip()
                if choice in ("a", "b", "t") and pid:
                    all_votes.append({
                        "pair_id": int(pid),
                        "voter": voter,
                        "choice": choice,
                    })
    return all_votes


def compute_stats(questionnaire: list, votes: list) -> dict:
    """计算胜率统计"""
    pair_map = {q["pair_id"]: q for q in questionnaire}

    agent_wins = 0
    baseline_wins = 0
    ties = 0
    total = len(votes)

    per_voter = {}

    for vote in votes:
        pid = vote["pair_id"]
        choice = vote["choice"]
        voter = vote["voter"]

        if voter not in per_voter:
            per_voter[voter] = {"agent": 0, "baseline": 0, "tie": 0, "total": 0}
        per_voter[voter]["total"] += 1

        if pid not in pair_map:
            continue

        pair = pair_map[pid]

        if choice == "t":
            ties += 1
            per_voter[voter]["tie"] += 1
        elif choice == "a":
            if pair["_hidden_a_source"] == "agent":
                agent_wins += 1
                per_voter[voter]["agent"] += 1
            else:
                baseline_wins += 1
                per_voter[voter]["baseline"] += 1
        elif choice == "b":
            if pair["_hidden_b_source"] == "agent":
                agent_wins += 1
                per_voter[voter]["agent"] += 1
            else:
                baseline_wins += 1
                per_voter[voter]["baseline"] += 1

    decisive = agent_wins + baseline_wins
    agent_winrate = agent_wins / decisive if decisive else 0
    baseline_winrate = baseline_wins / decisive if decisive else 0

    return {
        "total_votes": total,
        "agent_wins": agent_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "decisive_votes": decisive,
        "agent_winrate": agent_winrate,
        "baseline_winrate": baseline_winrate,
        "num_voters": len(per_voter),
        "per_voter": per_voter,
    }


def format_stats_report(stats: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("    解释质量 · A/B 盲测胜率报告")
    lines.append("=" * 60)
    lines.append(f"  评测人数:          {stats['num_voters']}")
    lines.append(f"  总投票数:          {stats['total_votes']}")
    lines.append("")
    lines.append(f"  ┌─────────────────────────────────────────────┐")
    lines.append(f"  │  Agent 胜出:      {stats['agent_wins']:>4d} 次  ({stats['agent_winrate']:.1%})     │")
    lines.append(f"  │  基线 胜出:       {stats['baseline_wins']:>4d} 次  ({stats['baseline_winrate']:.1%})     │")
    lines.append(f"  │  平手:            {stats['ties']:>4d} 次                    │")
    lines.append(f"  │                                               │")
    wl = "Agent 压倒性胜出" if stats["agent_winrate"] > 0.65 else (
        "Agent 优势明显" if stats["agent_winrate"] > 0.55 else (
            "两者接近" if stats["agent_winrate"] > 0.45 else "基线更优"))
    lines.append(f"  │  结论:  {wl:>20s}                │")
    lines.append(f"  └─────────────────────────────────────────────┘")
    lines.append("")

    if stats["per_voter"]:
        lines.append("-" * 60)
        lines.append("  各评测人投票分布:")
        lines.append(f"  {'评测人':>12s}  {'选Agent':>8s}  {'选基线':>8s}  {'平手':>4s}  {'总计':>4s}")
        lines.append("  " + "-" * 44)
        for voter, info in sorted(stats["per_voter"].items()):
            lines.append(
                f"  {voter:>10s}  {info['agent']:>8d}  {info['baseline']:>8d}  "
                f"{info['tie']:>4d}  {info['total']:>4d}"
            )
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def cmd_generate(args):
    """生成盲测问卷"""
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.abspath(args.agent), "r", encoding="utf-8") as f:
        agent_data = json.load(f)
    if isinstance(agent_data, dict) and "results" in agent_data:
        agent_data = agent_data["results"]

    with open(os.path.abspath(args.baseline), "r", encoding="utf-8") as f:
        baseline_data = json.load(f)
    if isinstance(baseline_data, dict) and "results" in baseline_data:
        baseline_data = baseline_data["results"]

    print(f"📂 Agent 结果: {len(agent_data)} 条")
    print(f"📂 基线结果:   {len(baseline_data)} 条")

    questionnaire = build_pairs(agent_data, baseline_data, args.sample)
    print(f"✅ 生成 {len(questionnaire)} 组盲测题")

    q_path = os.path.join(script_dir, QUESTIONNAIRE_FILE)
    with open(q_path, "w", encoding="utf-8") as f:
        json.dump(questionnaire, f, ensure_ascii=False, indent=2)
    print(f"💾 问卷已保存: {q_path}")


def cmd_evaluate(args):
    """执行盲测"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    q_path = os.path.join(script_dir, QUESTIONNAIRE_FILE)

    if not os.path.exists(q_path):
        print(f"❌ 问卷不存在: {q_path}")
        print("   请先运行: python3 abtest_blind_eval.py generate ...")
        sys.exit(1)

    with open(q_path, "r", encoding="utf-8") as f:
        questionnaire = json.load(f)

    if args.export_csv:
        csv_path = os.path.join(script_dir, CSV_EXPORT)
        export_csv_questionnaire(questionnaire, csv_path)
        return

    voter_name = input("请输入你的姓名/编号: ").strip() or "匿名"
    votes = interactive_evaluate(questionnaire, voter_name)

    votes_path = os.path.join(script_dir, VOTES_FILE)
    existing_votes = []
    if os.path.exists(votes_path):
        with open(votes_path, "r", encoding="utf-8") as f:
            existing_votes = json.load(f)

    existing_votes.extend(votes)
    with open(votes_path, "w", encoding="utf-8") as f:
        json.dump(existing_votes, f, ensure_ascii=False, indent=2)
    print(f"💾 投票已保存: {votes_path} (累计 {len(existing_votes)} 票)")


def cmd_stats(args):
    """统计胜率"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    q_path = os.path.join(script_dir, QUESTIONNAIRE_FILE)

    if not os.path.exists(q_path):
        print(f"❌ 问卷不存在: {q_path}")
        sys.exit(1)

    with open(q_path, "r", encoding="utf-8") as f:
        questionnaire = json.load(f)

    all_votes = []

    if args.import_csv:
        csv_votes = import_csv_votes(args.import_csv)
        all_votes.extend(csv_votes)
        print(f"📥 从 CSV 导入 {len(csv_votes)} 条投票")

    votes_path = os.path.join(script_dir, VOTES_FILE)
    if os.path.exists(votes_path):
        with open(votes_path, "r", encoding="utf-8") as f:
            json_votes = json.load(f)
        all_votes.extend(json_votes)
        print(f"📥 从 JSON 加载 {len(json_votes)} 条投票")

    if not all_votes:
        print("❌ 没有投票数据")
        sys.exit(1)

    stats = compute_stats(questionnaire, all_votes)
    report = format_stats_report(stats)
    print(report)

    report_path = os.path.join(script_dir, STATS_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="A/B 盲测：辟谣报告质量对比")
    subparsers = parser.add_subparsers(dest="command")

    gen_parser = subparsers.add_parser("generate", help="生成盲测问卷")
    gen_parser.add_argument("--agent", required=True, help="Agent 结果 JSON")
    gen_parser.add_argument("--baseline", required=True, help="基线结果 JSON")
    gen_parser.add_argument("--sample", type=int, default=SAMPLE_SIZE, help=f"抽取题数 (默认 {SAMPLE_SIZE})")

    eval_parser = subparsers.add_parser("evaluate", help="执行盲测投票")
    eval_parser.add_argument("--export-csv", action="store_true", help="导出 CSV 问卷")

    stats_parser = subparsers.add_parser("stats", help="统计胜率")
    stats_parser.add_argument("--import-csv", nargs="+", default=[], help="从 CSV 导入投票")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
