"""
依据溯源率 —— 第三步：计算溯源率

读取人工标注结果，计算依据溯源率及各维度指标，输出评估报告。

核心指标:
    依据溯源率 = 溯源成功数 / 已标注总数

用法:
    python3 calculate_faithfulness.py
    python3 calculate_faithfulness.py --input 溯源标注结果.json

输出:
    依据溯源率评估报告.txt  —— 完整评估报告
"""

import json
import argparse
import os
import sys
from collections import Counter

# ======================== 配置 ========================
INPUT_FILE = "溯源标注结果.json"
CASES_FILE = "溯源候选集.json"
OUTPUT_REPORT = "依据溯源率评估报告.txt"
OUTPUT_DETAIL = "依据溯源率详细结果.json"

LABEL_CN = {
    "sourced_success": "溯源成功",
    "sourced_conflict": "有线索但冲突",
    "no_evidence": "无实质线索",
    "hallucination": "幻觉/捏造",
}


def main():
    parser = argparse.ArgumentParser(description="计算依据溯源率")
    parser.add_argument("--input", default=INPUT_FILE, help="标注结果 JSON")
    parser.add_argument("--cases", default=CASES_FILE, help="候选集 JSON（补充原始文本）")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, args.input)
    cases_path = os.path.join(script_dir, args.cases)

    if not os.path.exists(input_path):
        print(f"❌ 标注结果文件不存在: {input_path}")
        print("   请先运行: python3 faithfulness_annotation.py")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    annotations = data.get("annotations", {})
    labeled = {k: v for k, v in annotations.items() if v.get("label")}

    if not labeled:
        print("❌ 没有已完成的标注记录")
        sys.exit(1)

    cases_map = {}
    if os.path.exists(cases_path):
        with open(cases_path, "r", encoding="utf-8") as f:
            cases = json.load(f)
        cases_map = {str(c["annotation_id"]): c for c in cases}

    total = len(labeled)
    label_counts = Counter(v["label"] for v in labeled.values())

    success_count = label_counts.get("sourced_success", 0)
    conflict_count = label_counts.get("sourced_conflict", 0)
    no_evidence_count = label_counts.get("no_evidence", 0)
    hallucination_count = label_counts.get("hallucination", 0)

    faithfulness_rate = success_count / total if total else 0.0
    has_source_rate = (success_count + conflict_count) / total if total else 0.0
    hallucination_rate = hallucination_count / total if total else 0.0

    lines = []
    lines.append("=" * 60)
    lines.append("    谣言智能体 · 依据溯源率 (Faithfulness) 评估报告")
    lines.append("=" * 60)
    lines.append(f"  标注样本数:        {total}")
    lines.append("")
    lines.append(f"  ┌─────────────────────────────────────────────┐")
    lines.append(f"  │  依据溯源率:      {faithfulness_rate:>6.1%}                    │")
    lines.append(f"  │  (溯源成功数 / 已标注总数)                    │")
    lines.append(f"  └─────────────────────────────────────────────┘")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  标注分布:")
    lines.append(f"  {'类别':>16s}  {'数量':>4s}  {'占比':>8s}  {'含义'}")
    lines.append("  " + "-" * 52)

    for label_key, cn_name in LABEL_CN.items():
        count = label_counts.get(label_key, 0)
        pct = count / total if total else 0
        marker = " ◀ 核心指标" if label_key == "sourced_success" else ""
        lines.append(f"  {cn_name:>14s}  {count:>4d}  {pct:>8.1%}  {marker}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("  衍生指标:")
    lines.append(f"    有源率 (包含外部线索):   {has_source_rate:.1%}")
    lines.append(f"      = (溯源成功 + 有线索但冲突) / 总数")
    lines.append(f"    幻觉率:                  {hallucination_rate:.1%}")
    lines.append(f"      = 幻觉捏造数 / 总数")
    lines.append("")

    if hallucination_count > 0:
        lines.append("-" * 60)
        lines.append("  幻觉案例（需重点关注）:")
        h_cases = [
            (k, v) for k, v in labeled.items()
            if v["label"] == "hallucination"
        ]
        for aid, ann in h_cases[:10]:
            case_info = cases_map.get(aid, {})
            text_preview = case_info.get("text", "")[:60]
            note = ann.get("note", "")
            lines.append(f"    [{aid}] {text_preview}...")
            if note:
                lines.append(f"         备注: {note}")
        if len(h_cases) > 10:
            lines.append(f"    ... 共 {len(h_cases)} 条")
        lines.append("")

    lines.append("-" * 60)
    lines.append("  结题报告话术参考:")
    lines.append("")
    lines.append(f'    "经人工核对 {total} 条 Agent 谣言判定案例，')
    lines.append(f'     依据溯源率达到 {faithfulness_rate:.1%}，')
    lines.append(f'     即 {success_count}/{total} 条辟谣结论均包含可验证的')
    lines.append(f'     外部权威来源，且引用内容与结论语义一致。')
    if hallucination_count > 0:
        lines.append(f'     幻觉率仅为 {hallucination_rate:.1%}。"')
    else:
        lines.append(f'     未发现幻觉捏造现象。"')
    lines.append("")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    report_path = os.path.join(script_dir, OUTPUT_REPORT)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_records = []
    for aid, ann in sorted(labeled.items(), key=lambda x: int(x[0])):
        case_info = cases_map.get(aid, {})
        detail_records.append({
            "annotation_id": int(aid),
            "text": case_info.get("text", ""),
            "true_label": case_info.get("true_label", ""),
            "agent_reason": case_info.get("agent_reason", ""),
            "faithfulness_label": ann["label"],
            "faithfulness_label_cn": ann.get("label_cn", ""),
            "note": ann.get("note", ""),
        })

    detail_output = {
        "metrics": {
            "total_annotated": total,
            "faithfulness_rate": round(faithfulness_rate, 4),
            "has_source_rate": round(has_source_rate, 4),
            "hallucination_rate": round(hallucination_rate, 4),
            "label_distribution": dict(label_counts),
        },
        "records": detail_records,
    }

    detail_path = os.path.join(script_dir, OUTPUT_DETAIL)
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2)
    print(f"📄 详细结果已保存: {detail_path}")


if __name__ == "__main__":
    main()
