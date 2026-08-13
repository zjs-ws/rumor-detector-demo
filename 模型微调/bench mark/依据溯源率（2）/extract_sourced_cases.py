"""
依据溯源率 —— 第一步：提取触发检索的谣言判定案例

从 Agent 评测的逐条结果中，筛选出：
  1. Agent 判定为谣言 (predicted_label == "rumor")
  2. 返回中包含外部证据线索（URL、年份、官方来源等）

输出可供人工标注的候选集。

用法:
    python3 extract_sourced_cases.py
    python3 extract_sourced_cases.py --input /path/to/早期预警逐条结果.json
    python3 extract_sourced_cases.py --sample 100

输出:
    溯源候选集.json         —— 供人工标注的案例
    溯源候选集_统计.txt      —— 提取统计
"""

import json
import re
import argparse
import os
import sys
from collections import Counter

# ======================== 配置 ========================
DEFAULT_INPUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "早期预警准确率", "Agent评测", "早期预警逐条结果.json"
)
OUTPUT_JSON = "溯源候选集.json"
OUTPUT_STATS = "溯源候选集_统计.txt"
DEFAULT_SAMPLE = 100

EVIDENCE_PATTERNS = [
    r"https?://\S+",
    r"(?:20[0-2]\d|19\d{2})年",
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
    r"官方|官网|政府|通报|公告|声明|新闻发布会",
    r"据.*(?:报道|消息|披露|透露|显示)",
    r"新华社|人民日报|央视|CCTV|新华网|中新网",
    r"(?:公安|警方|法院|检察|市场监管|卫健委|教育部|民政部)",
    r"(?:辟谣|证实|澄清|回应|否认)",
    r"根据.*?(?:数据|统计|调查|报告|研究)",
    r"fact[- ]?check|snopes|reuters|associated press",
]


def has_evidence(reason: str) -> dict:
    """检测 reason 字段中是否包含外部证据线索"""
    if not reason:
        return {"has_evidence": False, "evidence_types": [], "evidence_snippets": []}

    found_types = []
    found_snippets = []

    for pattern in EVIDENCE_PATTERNS:
        matches = re.findall(pattern, reason, re.IGNORECASE)
        if matches:
            label = pattern[:30].replace("\\", "")
            found_types.append(label)
            found_snippets.extend(matches[:3])

    return {
        "has_evidence": len(found_types) > 0,
        "evidence_types": found_types,
        "evidence_snippets": list(set(found_snippets)),
    }


def main():
    parser = argparse.ArgumentParser(description="提取触发检索的谣言判定案例")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Agent 逐条结果 JSON 路径")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="最多抽取 N 条 (0=全部)")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在: {input_path}")
        print("   请先运行 Agent 评测，生成逐条结果文件")
        print(f"   预期路径: {DEFAULT_INPUT}")
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

    rumor_cases = [r for r in results if r.get("predicted_label") == "rumor"]
    print(f"   其中 Agent 判定为谣言: {len(rumor_cases)} 条")

    candidates = []
    no_evidence_count = 0

    for item in rumor_cases:
        reason = item.get("reason", "")
        evidence_info = has_evidence(reason)

        candidate = {
            "original_index": item.get("index", -1),
            "text": item.get("text", ""),
            "true_label": item.get("true_label", ""),
            "predicted_label": item.get("predicted_label", ""),
            "risk_score": item.get("risk_score"),
            "agent_reason": reason,
            "auto_detected_evidence": evidence_info["has_evidence"],
            "evidence_types": evidence_info["evidence_types"],
            "evidence_snippets": evidence_info["evidence_snippets"],
        }
        candidates.append(candidate)

        if not evidence_info["has_evidence"]:
            no_evidence_count += 1

    with_evidence = [c for c in candidates if c["auto_detected_evidence"]]
    without_evidence = [c for c in candidates if not c["auto_detected_evidence"]]

    if args.sample > 0 and len(candidates) > args.sample:
        import random
        random.seed(42)
        n_with = min(len(with_evidence), int(args.sample * 0.7))
        n_without = min(len(without_evidence), args.sample - n_with)
        if n_with + n_without < args.sample:
            n_with = min(len(with_evidence), args.sample - n_without)
        sampled = random.sample(with_evidence, n_with) + random.sample(without_evidence, n_without)
        random.shuffle(sampled)
    else:
        sampled = candidates

    for i, item in enumerate(sampled):
        item["annotation_id"] = i + 1

    output_path = os.path.join(script_dir, OUTPUT_JSON)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sampled, f, ensure_ascii=False, indent=2)

    evidence_type_counter = Counter()
    for c in candidates:
        for t in c["evidence_types"]:
            evidence_type_counter[t] += 1

    stats_lines = [
        "=" * 55,
        "  依据溯源率 · 候选集提取报告",
        "=" * 55,
        f"  Agent 结果总数:           {len(results)}",
        f"  判定为谣言:               {len(rumor_cases)}",
        f"  自动检测到外部证据:       {len(with_evidence)}",
        f"  未检测到外部证据:         {no_evidence_count}",
        f"  抽样输出:                 {len(sampled)}",
        "-" * 55,
        "  证据类型分布:",
    ]
    for etype, count in evidence_type_counter.most_common():
        stats_lines.append(f"    {etype:30s}  {count:4d}")
    if not evidence_type_counter:
        stats_lines.append("    (无)")
    stats_lines.append("=" * 55)

    stats_text = "\n".join(stats_lines)
    print(stats_text)

    stats_path = os.path.join(script_dir, OUTPUT_STATS)
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write(stats_text + "\n")

    print(f"\n✅ 候选集已保存: {output_path}")
    print(f"✅ 统计已保存: {stats_path}")
    print(f"\n下一步: 运行 python3 faithfulness_annotation.py 进行人工标注")


if __name__ == "__main__":
    main()
