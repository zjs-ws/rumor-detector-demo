"""
依据溯源率 —— 第二步：人工标注工具

读取 extract_sourced_cases.py 生成的溯源候选集，
提供终端交互式标注界面，逐条判定是否"溯源成功"。

溯源成功的两个必要条件（必须同时满足）：
  ① 报告中包含明确的外部线索（官网链接、具体通报年份、权威来源等）
  ② 该线索内容与 Agent 的辟谣结论语义不冲突

用法:
    python3 faithfulness_annotation.py                 # 从头开始标注
    python3 faithfulness_annotation.py --resume        # 继续上次未完成的标注
    python3 faithfulness_annotation.py --export-csv    # 导出 CSV 方便多人协作

输出:
    溯源标注结果.json  —— 标注完成的数据
"""

import json
import os
import sys
import argparse
import csv

# ======================== 配置 ========================
INPUT_FILE = "溯源候选集.json"
OUTPUT_FILE = "溯源标注结果.json"
CSV_EXPORT_FILE = "溯源标注模板.csv"

ANNOTATION_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║                  依据溯源率 · 人工标注指南                     ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  对每条案例，你需要判断 Agent 的辟谣是否"有理有据"。            ║
║                                                              ║
║  标注选项：                                                   ║
║    [1] 溯源成功 — 同时满足以下两个条件：                        ║
║        ① 包含明确外部线索（官方链接/通报年份/权威来源引用）      ║
║        ② 线索与辟谣结论语义一致，没有自相矛盾                   ║
║                                                              ║
║    [2] 有线索但冲突 — 引用了外部来源，但内容与结论矛盾           ║
║        （例：引用的新闻其实支持原帖，Agent 却说是谣言）          ║
║                                                              ║
║    [3] 无实质线索 — 没有引用任何可验证的外部来源                  ║
║        （纯靠"常识推理"或"一般性陈述"做判断）                   ║
║                                                              ║
║    [4] 幻觉/捏造 — 引用了不存在的来源或编造了事实                ║
║        （例：捏造了一个不存在的官方通报）                        ║
║                                                              ║
║  操作：输入 1/2/3/4 后回车，可选输入备注                        ║
║  输入 s 跳过当前条，输入 q 保存并退出                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

LABEL_MAP = {
    "1": "sourced_success",
    "2": "sourced_conflict",
    "3": "no_evidence",
    "4": "hallucination",
}

LABEL_CN = {
    "sourced_success": "溯源成功",
    "sourced_conflict": "有线索但冲突",
    "no_evidence": "无实质线索",
    "hallucination": "幻觉/捏造",
}


def display_case(item: dict, total: int):
    """展示单条待标注案例"""
    idx = item["annotation_id"]
    print(f"\n{'─' * 60}")
    print(f"  [{idx}/{total}]")
    print(f"{'─' * 60}")
    print(f"  原帖文本:")
    print(f"    {item['text'][:200]}{'...' if len(item['text']) > 200 else ''}")
    print()
    print(f"  真实标签:     {item.get('true_label', '未知')}")
    print(f"  Agent 判定:   {item.get('predicted_label', '未知')}")
    if item.get("risk_score") is not None:
        print(f"  风险评分:     {item['risk_score']:.2f}")
    print()
    print(f"  Agent 辟谣理由:")
    reason = item.get("agent_reason", "(无)")
    if reason:
        for line in reason.split("\n"):
            print(f"    {line}")
    else:
        print("    (Agent 未返回推理理由)")
    print()
    if item.get("evidence_snippets"):
        print(f"  自动检测到的线索片段:")
        for s in item["evidence_snippets"][:5]:
            print(f"    • {s}")
    print(f"{'─' * 60}")


def interactive_annotate(cases: list, existing: dict) -> dict:
    """交互式标注"""
    print(ANNOTATION_GUIDE)
    total = len(cases)
    annotations = dict(existing)

    for item in cases:
        aid = str(item["annotation_id"])

        if aid in annotations and annotations[aid].get("label"):
            continue

        display_case(item, total)

        while True:
            choice = input("  标注 [1=溯源成功 2=有线索但冲突 3=无实质线索 4=幻觉] (s=跳过 q=保存退出): ").strip().lower()

            if choice == "q":
                print(f"\n💾 已保存 {len([v for v in annotations.values() if v.get('label')])} 条标注")
                return annotations
            elif choice == "s":
                break
            elif choice in LABEL_MAP:
                note = input("  备注 (可选，直接回车跳过): ").strip()
                annotations[aid] = {
                    "annotation_id": item["annotation_id"],
                    "label": LABEL_MAP[choice],
                    "label_cn": LABEL_CN[LABEL_MAP[choice]],
                    "note": note,
                }
                done = len([v for v in annotations.values() if v.get("label")])
                print(f"  ✅ 已标注 ({done}/{total})")
                break
            else:
                print("  ⚠️  请输入 1/2/3/4/s/q")

    print(f"\n🎉 全部 {total} 条标注完成！")
    return annotations


def export_csv(cases: list, output_path: str):
    """导出 CSV 模板，方便多人分工标注"""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "标注ID", "原帖文本", "真实标签", "Agent判定", "风险评分",
            "Agent辟谣理由", "自动检测线索",
            "标注结果(1=溯源成功/2=有线索但冲突/3=无实质线索/4=幻觉)",
            "备注"
        ])
        for item in cases:
            writer.writerow([
                item["annotation_id"],
                item["text"][:500],
                item.get("true_label", ""),
                item.get("predicted_label", ""),
                item.get("risk_score", ""),
                item.get("agent_reason", "")[:1000],
                "; ".join(item.get("evidence_snippets", [])),
                "",
                "",
            ])
    print(f"✅ CSV 标注模板已导出: {output_path}")
    print("   可用 Excel/WPS 打开，在'标注结果'列填写 1/2/3/4")


def import_csv_annotations(csv_path: str) -> dict:
    """从已填写的 CSV 导入标注结果"""
    annotations = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("标注ID", "").strip()
            label_val = row.get("标注结果(1=溯源成功/2=有线索但冲突/3=无实质线索/4=幻觉)", "").strip()
            note = row.get("备注", "").strip()

            if aid and label_val in LABEL_MAP:
                annotations[aid] = {
                    "annotation_id": int(aid),
                    "label": LABEL_MAP[label_val],
                    "label_cn": LABEL_CN[LABEL_MAP[label_val]],
                    "note": note,
                }
    return annotations


def main():
    parser = argparse.ArgumentParser(description="依据溯源率 · 人工标注工具")
    parser.add_argument("--input", default=INPUT_FILE, help="溯源候选集 JSON")
    parser.add_argument("--resume", action="store_true", help="继续上次未完成的标注")
    parser.add_argument("--export-csv", action="store_true", help="导出 CSV 标注模板")
    parser.add_argument("--import-csv", default="", help="从已填写的 CSV 导入标注结果")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, args.input)

    if not os.path.exists(input_path):
        print(f"❌ 候选集文件不存在: {input_path}")
        print("   请先运行: python3 extract_sourced_cases.py")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"📋 候选集已加载: {len(cases)} 条")

    if args.export_csv:
        csv_path = os.path.join(script_dir, CSV_EXPORT_FILE)
        export_csv(cases, csv_path)
        return

    if args.import_csv:
        csv_path = os.path.abspath(args.import_csv)
        if not os.path.exists(csv_path):
            print(f"❌ CSV 文件不存在: {csv_path}")
            sys.exit(1)
        annotations = import_csv_annotations(csv_path)
        print(f"📥 从 CSV 导入 {len(annotations)} 条标注")
    elif args.resume:
        output_path = os.path.join(script_dir, OUTPUT_FILE)
        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            annotations = saved.get("annotations", {})
            done = len([v for v in annotations.values() if v.get("label")])
            print(f"📂 恢复上次进度: 已标注 {done}/{len(cases)} 条")
        else:
            annotations = {}
    else:
        annotations = {}

    if not args.import_csv:
        annotations = interactive_annotate(cases, annotations)

    output_data = {
        "total_cases": len(cases),
        "annotated_count": len([v for v in annotations.values() if v.get("label")]),
        "annotations": annotations,
    }

    output_path = os.path.join(script_dir, OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"💾 标注结果已保存: {output_path}")
    print(f"   已标注: {output_data['annotated_count']}/{len(cases)}")
    print(f"\n下一步: 运行 python3 calculate_faithfulness.py 计算溯源率")


if __name__ == "__main__":
    main()
