"""
解释质量与自洽度 —— 量化条件 1：打分与解释的自洽性检测

检查 Agent 返回的多维打分（雷达图各维度）与 reason 字段的一致性。
如果某个维度打了高分，但 reason 中找不到对应的支撑论据，记为"不自洽"。

用法:
    python3 check_consistency.py --input agent_results.json
    python3 check_consistency.py --input agent_results.json --threshold 70

输入格式:
    Agent 接口返回的 JSON，需包含多维打分和 reason。
    支持以下两种格式（脚本自动识别）：

    格式 A — 独立字段:
    {
        "text": "...",
        "predicted_label": "rumor",
        "scores": {
            "情绪煽动": 90,
            "逻辑漏洞": 75,
            "事实偏差": 85,
            "来源可疑": 60,
            "时效过期": 30
        },
        "reason": "该文本使用了大量感叹号和夸张词汇..."
    }

    格式 B — 逐条结果列表 (指标一输出):
    [{"text": "...", "risk_score": 0.9, "reason": "...", ...}, ...]

输出:
    自洽性检测报告.txt
    自洽性逐条结果.json
"""

import json
import re
import argparse
import os
import sys
from collections import Counter, defaultdict

# ======================== 维度关键词映射 ========================
# 每个评分维度应当在 reason 中出现的支撑关键词
DIMENSION_KEYWORDS = {
    "情绪煽动": [
        r"感叹号|！{2,}|!{2,}",
        r"夸张|煽动|耸人听闻|震惊|惊爆|疯传|速看|转疯",
        r"情绪|情感|激烈|愤怒|恐慌|焦虑",
        r"紧急|马上|立刻|赶紧|一定要看",
        r"词汇.*(?:强烈|极端|过度)",
    ],
    "逻辑漏洞": [
        r"逻辑|矛盾|不一致|自相矛盾|前后.*矛盾",
        r"推理|论证|因果|论据不足",
        r"以偏概全|偷换概念|滑坡谬误|稻草人",
        r"缺乏.*(?:依据|证据|支撑)",
        r"无法.*(?:推出|得出|证明)",
    ],
    "事实偏差": [
        r"事实|真相|实际|实情",
        r"数据.*(?:错误|偏差|不符|失实)",
        r"查证|核实|验证|不实",
        r"篡改|歪曲|误导|失真",
        r"与.*(?:不符|相反|矛盾)",
    ],
    "来源可疑": [
        r"来源|出处|消息源|信源",
        r"匿名|不明|未经证实|据说|传闻|网传",
        r"可信度|权威|官方|不可靠",
        r"(?:无法|难以).*(?:追溯|查证|核实)",
        r"杜撰|捏造|伪造",
    ],
    "时效过期": [
        r"时间|日期|过期|过时|旧闻",
        r"(?:20\d{2}|19\d{2}).*(?:年|月)",
        r"已.*(?:辟谣|澄清|更正|撤回)",
        r"翻炒|老谣|旧帖|陈年",
        r"时效|时间线|不再.*(?:适用|有效)",
    ],
    "传播异常": [
        r"传播|扩散|转发|分享",
        r"水军|刷量|异常.*(?:增长|传播)",
        r"机器人|bot|自动化",
        r"短时间.*(?:大量|快速|爆发)",
        r"(?:转发|评论|点赞).*(?:异常|可疑)",
    ],
}

DEFAULT_THRESHOLD = 70


def check_single_dimension(dimension: str, score: float, reason: str) -> dict:
    """检查单个维度的打分与 reason 是否自洽"""
    keywords = DIMENSION_KEYWORDS.get(dimension, [])
    if not keywords:
        return {"consistent": True, "detail": "未配置关键词，跳过检查"}

    matched_keywords = []
    for pattern in keywords:
        if re.search(pattern, reason, re.IGNORECASE):
            matches = re.findall(pattern, reason, re.IGNORECASE)
            matched_keywords.extend(matches[:2])

    has_support = len(matched_keywords) > 0

    if score >= DEFAULT_THRESHOLD and not has_support:
        return {
            "consistent": False,
            "detail": f"打分 {score} 分 (≥{DEFAULT_THRESHOLD})，但 reason 中未找到相关论据",
            "matched": [],
        }
    elif score < DEFAULT_THRESHOLD * 0.4 and has_support:
        return {
            "consistent": True,
            "detail": f"打分 {score} 分，reason 中有相关提及（低分合理）",
            "matched": matched_keywords,
            "note": "低分但有提及，可能是排除性说明",
        }
    else:
        return {
            "consistent": True,
            "detail": f"打分 {score} 分，自洽",
            "matched": matched_keywords,
        }


def extract_scores(item: dict) -> dict:
    """从不同格式的 Agent 返回中提取多维打分"""
    if "scores" in item and isinstance(item["scores"], dict):
        return item["scores"]

    if "dimensions" in item and isinstance(item["dimensions"], dict):
        return item["dimensions"]

    if "radar" in item and isinstance(item["radar"], dict):
        return item["radar"]

    if "risk_score" in item and item.get("reason"):
        return {"综合风险": float(item["risk_score"]) * 100 if item["risk_score"] <= 1 else item["risk_score"]}

    score_fields = {}
    for key, val in item.items():
        if isinstance(val, (int, float)) and key not in ("index", "annotation_id", "original_index"):
            if 0 <= val <= 100 or (0 <= val <= 1):
                normalized = val * 100 if val <= 1 else val
                score_fields[key] = normalized
    return score_fields


def analyze_results(results: list, threshold: int) -> dict:
    """分析全部结果的自洽性"""
    global DEFAULT_THRESHOLD
    DEFAULT_THRESHOLD = threshold

    all_checks = []
    dimension_stats = defaultdict(lambda: {"total": 0, "consistent": 0, "inconsistent": 0})

    for item in results:
        scores = extract_scores(item)
        reason = item.get("reason", "") or item.get("agent_reason", "") or ""
        text = item.get("text", "")

        if not scores:
            continue

        item_checks = {
            "index": item.get("index", -1),
            "text": text[:100],
            "scores": scores,
            "reason_preview": reason[:200],
            "dimensions": {},
            "is_fully_consistent": True,
        }

        for dim, score in scores.items():
            result = check_single_dimension(dim, score, reason)
            item_checks["dimensions"][dim] = result
            dimension_stats[dim]["total"] += 1
            if result["consistent"]:
                dimension_stats[dim]["consistent"] += 1
            else:
                dimension_stats[dim]["inconsistent"] += 1
                item_checks["is_fully_consistent"] = False

        all_checks.append(item_checks)

    total_items = len(all_checks)
    fully_consistent = sum(1 for c in all_checks if c["is_fully_consistent"])
    total_dim_checks = sum(s["total"] for s in dimension_stats.values())
    total_dim_consistent = sum(s["consistent"] for s in dimension_stats.values())

    return {
        "total_items": total_items,
        "fully_consistent_items": fully_consistent,
        "item_consistency_rate": fully_consistent / total_items if total_items else 0,
        "total_dimension_checks": total_dim_checks,
        "total_dimension_consistent": total_dim_consistent,
        "dimension_consistency_rate": total_dim_consistent / total_dim_checks if total_dim_checks else 0,
        "per_dimension": {
            dim: {
                "total": s["total"],
                "consistent": s["consistent"],
                "inconsistent": s["inconsistent"],
                "rate": s["consistent"] / s["total"] if s["total"] else 0,
            }
            for dim, s in dimension_stats.items()
        },
        "details": all_checks,
    }


def format_report(metrics: dict, threshold: int) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("    解释质量与自洽度 · 打分-解释自洽性检测报告")
    lines.append("=" * 60)
    lines.append(f"  高分阈值:          ≥{threshold} 分")
    lines.append(f"  检测样本数:        {metrics['total_items']}")
    lines.append("")
    lines.append(f"  ┌─────────────────────────────────────────────┐")
    lines.append(f"  │  样本级自洽率:    {metrics['item_consistency_rate']:>6.1%}                    │")
    lines.append(f"  │  (全部维度均自洽的样本占比)                    │")
    lines.append(f"  │                                               │")
    lines.append(f"  │  维度级自洽率:    {metrics['dimension_consistency_rate']:>6.1%}                    │")
    lines.append(f"  │  (所有维度检测中自洽的占比)                    │")
    lines.append(f"  └─────────────────────────────────────────────┘")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  各维度自洽率:")
    lines.append(f"  {'维度':>12s}  {'检测数':>6s}  {'自洽':>4s}  {'不自洽':>6s}  {'自洽率':>8s}")
    lines.append("  " + "-" * 48)
    for dim, info in sorted(metrics["per_dimension"].items(), key=lambda x: x[1]["rate"]):
        lines.append(
            f"  {dim:>10s}  {info['total']:>6d}  {info['consistent']:>4d}  "
            f"{info['inconsistent']:>6d}  {info['rate']:>8.1%}"
        )
    lines.append("")

    inconsistent_examples = [
        d for d in metrics["details"] if not d["is_fully_consistent"]
    ]
    if inconsistent_examples:
        lines.append("-" * 60)
        lines.append(f"  不自洽案例（共 {len(inconsistent_examples)} 条，展示前 5 条）:")
        for ex in inconsistent_examples[:5]:
            lines.append(f"    [{ex['index']}] {ex['text']}...")
            for dim, info in ex["dimensions"].items():
                if not info["consistent"]:
                    lines.append(f"         {dim}: {info['detail']}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="打分与解释的自洽性检测")
    parser.add_argument("--input", required=True, help="Agent 结果 JSON 文件路径")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help=f"高分阈值 (默认 {DEFAULT_THRESHOLD})")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.abspath(args.input)

    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "results" in data:
        results = data["results"]
    elif isinstance(data, list):
        results = data
    else:
        print("❌ 无法识别输入文件格式")
        sys.exit(1)

    print(f"📂 读取 Agent 结果: {input_path}")
    print(f"   共 {len(results)} 条记录")
    print(f"   高分阈值: ≥{args.threshold}")

    metrics = analyze_results(results, args.threshold)
    report = format_report(metrics, args.threshold)
    print(report)

    report_path = os.path.join(script_dir, "自洽性检测报告.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_path = os.path.join(script_dir, "自洽性逐条结果.json")
    detail_output = {
        "config": {"threshold": args.threshold},
        "metrics": {k: v for k, v in metrics.items() if k != "details"},
        "details": metrics["details"],
    }
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2)
    print(f"📄 逐条结果已保存: {detail_path}")


if __name__ == "__main__":
    main()
