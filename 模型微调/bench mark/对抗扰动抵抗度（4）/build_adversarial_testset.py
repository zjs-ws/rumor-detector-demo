"""
对抗扰动抵抗度 —— 第一步：构造对抗性"脏数据"测试集

对指标一的纯净测试集施加多种真实世界中造谣者常用的文本伪装手段，
生成一份"脏版"测试集。与纯净版对比，衡量模型的抗干扰能力。

扰动类型：
  1. 谐音替换 —— "辟谣" -> "辟瑶"，"政府" -> "正付"
  2. 字符穿插 —— "爆发" -> "爆 发"，"H7N9" -> "H-7-N-9"
  3. 同音拼音 —— "疫情" -> "yì qíng"
  4. 视觉混淆 —— "o" -> "0"，"l" -> "1"
  5. emoji 干扰 —— 在关键词间插入 emoji
  6. 繁简混排 —— 随机将部分简体字转为繁体

用法:
    python3 build_adversarial_testset.py
    python3 build_adversarial_testset.py --intensity medium
    python3 build_adversarial_testset.py --intensity heavy

输出:
    对抗测试集.json       —— 扰动后的脏数据
    对抗测试集_统计.txt    —— 扰动统计
"""

import json
import random
import re
import os
import sys
from collections import Counter

# ======================== 配置 ========================
SOURCE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "早期预警准确率（1）", "早期预警测试集.json"
)
OUTPUT_JSON = "对抗测试集.json"
OUTPUT_STATS = "对抗测试集_统计.txt"
RANDOM_SEED = 42

# ======================== 扰动词典 ========================
HOMOPHONE_MAP_ZH = {
    "政府": "正付", "辟谣": "辟瑶", "疫情": "役情", "爆发": "暴发",
    "确诊": "确珍", "死亡": "似亡", "感染": "敢染", "病毒": "并毒",
    "封城": "风城", "隔离": "格力", "核酸": "河酸", "阳性": "洋性",
    "官方": "管方", "通报": "通宝", "警方": "井方", "医院": "一元",
    "专家": "砖家", "研究": "烟酒", "教育": "叫鱼", "考试": "烤试",
    "取消": "娶消", "严重": "盐重", "紧急": "金鸡", "危险": "围险",
    "食品": "时品", "安全": "按全", "污染": "巫染", "有毒": "油毒",
    "地震": "低震", "台风": "抬风", "洪水": "红水", "灾难": "宰难",
}

VISUAL_CONFUSE = {
    "o": "0", "O": "0", "l": "1", "I": "1",
    "a": "@", "e": "3", "s": "$", "g": "9",
    "B": "8", "A": "4",
}

SEPARATOR_CHARS = [" ", "·", "-", ".", "_", "~", "*"]

EMOJI_LIST = ["🔥", "⚠️", "❗", "💀", "😱", "🚨", "‼️", "👀", "💣", "🆘"]

SIMP_TO_TRAD = {
    "国": "國", "学": "學", "发": "發", "会": "會", "时": "時",
    "为": "為", "个": "個", "这": "這", "们": "們", "来": "來",
    "对": "對", "说": "說", "与": "與", "经": "經", "过": "過",
    "问": "問", "现": "現", "长": "長", "开": "開", "进": "進",
    "关": "關", "点": "點", "动": "動", "实": "實", "东": "東",
    "报": "報", "没": "沒", "机": "機", "认": "認", "请": "請",
    "该": "該", "两": "兩", "广": "廣", "号": "號", "车": "車",
}


def perturb_homophone_zh(text: str, prob: float = 0.3) -> tuple[str, int]:
    """谐音替换（中文）"""
    count = 0
    for original, replacement in HOMOPHONE_MAP_ZH.items():
        if original in text and random.random() < prob:
            text = text.replace(original, replacement, 1)
            count += 1
    return text, count


def perturb_char_insert(text: str, prob: float = 0.15) -> tuple[str, int]:
    """字符穿插：在中文字之间插入分隔符"""
    chars = list(text)
    new_chars = []
    count = 0
    for i, ch in enumerate(chars):
        new_chars.append(ch)
        if i < len(chars) - 1 and '\u4e00' <= ch <= '\u9fff' and '\u4e00' <= chars[i + 1] <= '\u9fff':
            if random.random() < prob:
                new_chars.append(random.choice(SEPARATOR_CHARS))
                count += 1
    return "".join(new_chars), count


def perturb_visual_en(text: str, prob: float = 0.2) -> tuple[str, int]:
    """视觉混淆（英文字母）"""
    chars = list(text)
    count = 0
    for i, ch in enumerate(chars):
        if ch in VISUAL_CONFUSE and random.random() < prob:
            chars[i] = VISUAL_CONFUSE[ch]
            count += 1
    return "".join(chars), count


def perturb_emoji_insert(text: str, prob: float = 0.1) -> tuple[str, int]:
    """在文本中随机插入 emoji 干扰"""
    words = text.split()
    new_words = []
    count = 0
    for w in words:
        new_words.append(w)
        if random.random() < prob:
            new_words.append(random.choice(EMOJI_LIST))
            count += 1
    return " ".join(new_words), count


def perturb_simp_to_trad(text: str, prob: float = 0.2) -> tuple[str, int]:
    """繁简混排"""
    chars = list(text)
    count = 0
    for i, ch in enumerate(chars):
        if ch in SIMP_TO_TRAD and random.random() < prob:
            chars[i] = SIMP_TO_TRAD[ch]
            count += 1
    return "".join(chars), count


def perturb_number_split(text: str) -> tuple[str, int]:
    """数字穿插：H7N9 -> H-7-N-9"""
    count = 0
    def split_alphanumeric(match):
        nonlocal count
        s = match.group()
        if len(s) >= 3:
            count += 1
            return "-".join(s)
        return s
    text = re.sub(r"[A-Za-z]\d[A-Za-z]\d", split_alphanumeric, text)
    return text, count


INTENSITY_CONFIG = {
    "light": {
        "homophone_prob": 0.15,
        "char_insert_prob": 0.08,
        "visual_prob": 0.1,
        "emoji_prob": 0.05,
        "trad_prob": 0.1,
        "max_perturbations": 2,
    },
    "medium": {
        "homophone_prob": 0.3,
        "char_insert_prob": 0.15,
        "visual_prob": 0.2,
        "emoji_prob": 0.1,
        "trad_prob": 0.2,
        "max_perturbations": 4,
    },
    "heavy": {
        "homophone_prob": 0.5,
        "char_insert_prob": 0.25,
        "visual_prob": 0.35,
        "emoji_prob": 0.15,
        "trad_prob": 0.3,
        "max_perturbations": 6,
    },
}


def apply_perturbations(text: str, intensity: str = "medium") -> dict:
    """对单条文本施加组合扰动"""
    cfg = INTENSITY_CONFIG[intensity]
    perturbation_log = {}
    total_changes = 0

    has_zh = bool(re.search(r'[\u4e00-\u9fff]', text))

    if has_zh:
        text, n = perturb_homophone_zh(text, cfg["homophone_prob"])
        if n: perturbation_log["谐音替换"] = n
        total_changes += n

        text, n = perturb_char_insert(text, cfg["char_insert_prob"])
        if n: perturbation_log["字符穿插"] = n
        total_changes += n

        text, n = perturb_simp_to_trad(text, cfg["trad_prob"])
        if n: perturbation_log["繁简混排"] = n
        total_changes += n
    else:
        text, n = perturb_visual_en(text, cfg["visual_prob"])
        if n: perturbation_log["视觉混淆"] = n
        total_changes += n

        text, n = perturb_number_split(text)
        if n: perturbation_log["数字穿插"] = n
        total_changes += n

    text, n = perturb_emoji_insert(text, cfg["emoji_prob"])
    if n: perturbation_log["emoji干扰"] = n
    total_changes += n

    return {
        "perturbed_text": text,
        "perturbation_log": perturbation_log,
        "total_changes": total_changes,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="构造对抗性脏数据测试集")
    parser.add_argument("--input", default=SOURCE_FILE, help="纯净测试集路径")
    parser.add_argument("--intensity", default="medium", choices=["light", "medium", "heavy"],
                        help="扰动强度 (默认 medium)")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.exists(input_path):
        print(f"❌ 纯净测试集不存在: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        clean_data = json.load(f)
    print(f"📂 读取纯净测试集: {len(clean_data)} 条")
    print(f"🎚️  扰动强度: {args.intensity}")

    random.seed(RANDOM_SEED)

    adversarial_data = []
    perturbation_type_counter = Counter()

    for item in clean_data:
        original_text = item["text"]
        result = apply_perturbations(original_text, args.intensity)

        record = {
            "text": result["perturbed_text"],
            "original_text": original_text,
            "true_label": item["true_label"],
            "perturbation_log": result["perturbation_log"],
            "total_changes": result["total_changes"],
        }
        adversarial_data.append(record)

        for ptype in result["perturbation_log"]:
            perturbation_type_counter[ptype] += 1

    output_path = os.path.join(script_dir, OUTPUT_JSON)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(adversarial_data, f, ensure_ascii=False, indent=2)

    changed = sum(1 for d in adversarial_data if d["total_changes"] > 0)
    avg_changes = sum(d["total_changes"] for d in adversarial_data) / len(adversarial_data)

    stats_lines = [
        "=" * 55,
        "  对抗扰动测试集 构建报告",
        "=" * 55,
        f"  源测试集:         {os.path.basename(input_path)}",
        f"  扰动强度:         {args.intensity}",
        f"  总样本数:         {len(adversarial_data)}",
        f"  被扰动样本数:     {changed} ({changed / len(adversarial_data) * 100:.1f}%)",
        f"  平均扰动次数:     {avg_changes:.1f}",
        "-" * 55,
        "  扰动类型分布:",
    ]
    for ptype, count in perturbation_type_counter.most_common():
        stats_lines.append(f"    {ptype:12s}  影响 {count:4d} 条样本")
    stats_lines.append("=" * 55)
    stats_lines.append("")
    stats_lines.append("  扰动示例:")
    for d in adversarial_data[:5]:
        if d["total_changes"] > 0:
            stats_lines.append(f"    原文: {d['original_text'][:50]}...")
            stats_lines.append(f"    脏版: {d['text'][:50]}...")
            stats_lines.append(f"    变更: {d['perturbation_log']}")
            stats_lines.append("")

    stats_text = "\n".join(stats_lines)
    print(stats_text)

    stats_path = os.path.join(script_dir, OUTPUT_STATS)
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write(stats_text + "\n")

    print(f"✅ 对抗测试集已保存: {output_path}")
    print(f"✅ 统计报告已保存: {stats_path}")


if __name__ == "__main__":
    main()
