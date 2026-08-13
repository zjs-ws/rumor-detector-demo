"""
端到端决断延迟 —— 第一步：构造延迟基准测试集

从原始数据中按文本长度和语言分层抽样，
确保覆盖短/中/长文本和中/英文，
以便分析延迟与文本复杂度的关系。

用法:
    python3 build_latency_testset.py
    python3 build_latency_testset.py --sample 60

输出:
    延迟测试集.json      —— 分层抽样的测试数据（含长度分桶标签）
    延迟测试集_统计.txt   —— 统计报告
"""

import json
import random
import re
import os
import sys

# ======================== 配置 ========================
SOURCE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "原测试集", "Combined_Shuffled_Dataset_V_Augmented.json"
)
OUTPUT_JSON = "延迟测试集.json"
OUTPUT_STATS = "延迟测试集_统计.txt"
DEFAULT_SAMPLE = 60
RANDOM_SEED = 2024

LENGTH_BUCKETS = [
    ("短文本", 0, 50),
    ("中文本", 50, 150),
    ("长文本", 150, 999999),
]

SYNTHETIC_COMPLEX = [
    {
        "text": (
            "网传某市自来水中检测出大量氯化物超标，多个小区居民出现皮肤过敏症状。"
            "据称该市水务局已紧急停水检修，但官方尚未发布通报。"
            "有居民拍摄视频显示水龙头流出的水呈黄色浑浊状态，"
            "并声称多名儿童饮水后出现腹泻症状被送医。"
            "环保组织呼吁政府公开水质检测数据。"
        ),
        "true_label": "rumor",
        "complexity": "high",
        "note": "多线索长文本，需要多次外部查证",
    },
    {
        "text": (
            "breaking: a leaked internal document from a major tech company "
            "reveals plans to lay off 15,000 employees globally. "
            "the document, allegedly signed by the ceo, outlines cost-cutting "
            "measures including closing 3 research labs and freezing all hiring. "
            "company stock dropped 8% in after-hours trading. "
            "a spokesperson declined to comment on the leaked memo."
        ),
        "true_label": "unknown",
        "complexity": "high",
        "note": "英文长文本，涉及多个可验证事实",
    },
    {
        "text": "刚刚收到消息，本市今晚将实施临时交通管制。",
        "true_label": "unknown",
        "complexity": "low",
        "note": "极短文本，模拟最快响应场景",
    },
]


def strip_social_signals(text: str) -> str:
    text = re.sub(r"@[\w\u4e00-\u9fff]+", "", text)
    text = re.sub(r"<\s*(?:url|@user|link|img|pic)\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#[^#\s]+#?", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_language(text: str) -> str:
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return "zh" if cn_chars > len(text) * 0.15 else "en"


def get_length_bucket(text_len: int) -> str:
    for name, lo, hi in LENGTH_BUCKETS:
        if lo <= text_len < hi:
            return name
    return "长文本"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="构造延迟基准测试集")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"总抽样数 (默认 {DEFAULT_SAMPLE})")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.abspath(SOURCE_FILE)

    if not os.path.exists(source_path):
        print(f"❌ 源数据不存在: {source_path}")
        sys.exit(1)

    with open(source_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    print(f"📂 读取源数据: {len(raw_data)} 条")

    label_map = {"Yes": "rumor", "No": "non_rumor", "Unknown": "unknown"}
    cleaned = []
    for item in raw_data:
        text = strip_social_signals(item.get("input", ""))
        if len(text) < 8:
            continue
        true_label = label_map.get(item.get("output", "").strip(), "unknown")
        lang = detect_language(text)
        bucket = get_length_bucket(len(text))
        cleaned.append({
            "text": text,
            "true_label": true_label,
            "char_length": len(text),
            "language": lang,
            "length_bucket": bucket,
        })

    random.seed(RANDOM_SEED)

    pools = {}
    for item in cleaned:
        key = (item["length_bucket"], item["language"])
        pools.setdefault(key, []).append(item)

    n_synthetic = len(SYNTHETIC_COMPLEX)
    n_from_data = args.sample - n_synthetic

    allocation = {}
    for key, pool in pools.items():
        allocation[key] = max(2, int(n_from_data * len(pool) / len(cleaned)))

    total_alloc = sum(allocation.values())
    if total_alloc < n_from_data:
        biggest_key = max(allocation, key=lambda k: len(pools[k]))
        allocation[biggest_key] += n_from_data - total_alloc
    elif total_alloc > n_from_data:
        biggest_key = max(allocation, key=lambda k: allocation[k])
        allocation[biggest_key] -= total_alloc - n_from_data

    selected = []
    for key, n in allocation.items():
        pool = pools.get(key, [])
        n = min(n, len(pool))
        selected.extend(random.sample(pool, n))

    for item in SYNTHETIC_COMPLEX:
        text = item["text"]
        selected.append({
            "text": text,
            "true_label": item["true_label"],
            "char_length": len(text),
            "language": detect_language(text),
            "length_bucket": get_length_bucket(len(text)),
            "complexity": item.get("complexity", "normal"),
            "note": item.get("note", ""),
        })

    random.shuffle(selected)
    for i, item in enumerate(selected):
        item["index"] = i

    output_path = os.path.join(script_dir, OUTPUT_JSON)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)

    from collections import Counter
    bucket_counts = Counter(s["length_bucket"] for s in selected)
    lang_counts = Counter(s["language"] for s in selected)
    label_counts = Counter(s["true_label"] for s in selected)
    char_lens = [s["char_length"] for s in selected]

    stats_lines = [
        "=" * 55,
        "  延迟基准测试集 构建报告",
        "=" * 55,
        f"  总样本数:       {len(selected)}",
        f"  字符长度范围:   {min(char_lens)} ~ {max(char_lens)}",
        f"  平均长度:       {sum(char_lens)/len(char_lens):.0f} 字符",
        "",
        "  按文本长度分布:",
        *[f"    {b:>6s}: {bucket_counts.get(b, 0):>3d} 条" for b, _, _ in LENGTH_BUCKETS],
        "",
        "  按语言分布:",
        *[f"    {l:>4s}: {c:>3d} 条" for l, c in sorted(lang_counts.items())],
        "",
        "  按标签分布:",
        *[f"    {l:>12s}: {c:>3d} 条" for l, c in sorted(label_counts.items())],
        "",
        f"  合成复杂样本:   {n_synthetic} 条",
        "-" * 55,
        "  设计意图:",
        "    分层覆盖不同文本长度和语言，便于分析",
        "    Agent 端到端延迟与输入复杂度的关系。",
        "=" * 55,
    ]
    stats_text = "\n".join(stats_lines)
    print(stats_text)

    stats_path = os.path.join(script_dir, OUTPUT_STATS)
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write(stats_text + "\n")

    print(f"\n✅ 测试集已保存: {output_path}")
    print(f"✅ 统计已保存: {stats_path}")


if __name__ == "__main__":
    main()
