"""
早期预警准确率 —— 第一步：构造"极端苛刻"的纯文本测试集

从测试集中随机抽取 200 条数据，物理切断所有传播链信息
（@用户、URL、转发/点赞数字前缀、话题标签等），
只保留原始文本和真实标签，模拟谣言刚发布第 1 秒的状态。

用法:
    python build_early_warning_testset.py

输出:
    早期预警测试集.json   —— 200 条纯文本记录
    早期预警测试集_统计.txt —— 标签分布摘要
"""

import json
import random
import re
import os
from collections import Counter

# ======================== 配置 ========================
SOURCE_FILE = os.path.join("..", "原测试集", "Combined_Shuffled_Dataset_V_Augmented.json")
OUTPUT_JSON = "早期预警测试集.json"
OUTPUT_STATS = "早期预警测试集_统计.txt"
SAMPLE_SIZE = 200
RANDOM_SEED = 42

LABEL_MAP = {
    "Yes": "rumor",
    "No": "non_rumor",
    "Unknown": "unknown",
}


def strip_social_signals(text: str) -> str:
    """物理切断所有传播链 / 社交网络信号"""

    # 移除 @用户 提及（中英文均覆盖）
    text = re.sub(r"@[\w\u4e00-\u9fff]+", "", text)

    # 移除 <url> / <@user> 等占位符标记
    text = re.sub(r"<\s*(?:url|@user|link|img|pic)\s*>", "", text, flags=re.IGNORECASE)

    # 移除 http(s) 链接
    text = re.sub(r"https?://\S+", "", text)

    # 移除 #话题标签#（微博风格）和 #hashtag（Twitter 风格）
    text = re.sub(r"#[^#\s]+#?", "", text)

    # 移除 "转发微博" / "转发了" 等转发标记
    text = re.sub(r"转发(微博|了)?", "", text)

    # 移除 "[转]" "[赞]" 等方括号标记
    text = re.sub(r"\[转\]|\[赞\]|\[评\]", "", text)

    # 清理多余空白
    text = re.sub(r"\s+", " ", text).strip()

    return text


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.join(script_dir, SOURCE_FILE)

    print(f"📂 读取源数据: {source_path}")
    with open(source_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    print(f"   共 {len(raw_data)} 条记录")

    random.seed(RANDOM_SEED)
    sampled = random.sample(raw_data, min(SAMPLE_SIZE, len(raw_data)))

    clean_records = []
    skipped = 0

    for item in sampled:
        original_text = item.get("input", "")
        label_raw = item.get("output", "").strip()

        cleaned_text = strip_social_signals(original_text)

        if len(cleaned_text) < 4:
            skipped += 1
            continue

        true_label = LABEL_MAP.get(label_raw, label_raw.lower())

        clean_records.append({
            "text": cleaned_text,
            "true_label": true_label,
        })

    output_json_path = os.path.join(script_dir, OUTPUT_JSON)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=2)

    label_counts = Counter(r["true_label"] for r in clean_records)
    stats_lines = [
        "=" * 50,
        "  早期预警测试集 构建报告",
        "=" * 50,
        f"  源数据集:     {SOURCE_FILE}",
        f"  源数据总量:   {len(raw_data)}",
        f"  抽样数量:     {SAMPLE_SIZE}",
        f"  有效记录:     {len(clean_records)}",
        f"  跳过 (文本过短): {skipped}",
        "-" * 50,
        "  标签分布:",
    ]
    for label, count in sorted(label_counts.items()):
        pct = count / len(clean_records) * 100
        stats_lines.append(f"    {label:12s}  {count:4d}  ({pct:.1f}%)")
    stats_lines.append("=" * 50)

    stats_text = "\n".join(stats_lines)
    print(stats_text)

    output_stats_path = os.path.join(script_dir, OUTPUT_STATS)
    with open(output_stats_path, "w", encoding="utf-8") as f:
        f.write(stats_text + "\n")

    print(f"\n✅ 测试集已保存: {output_json_path}")
    print(f"✅ 统计报告已保存: {output_stats_path}")


if __name__ == "__main__":
    main()
