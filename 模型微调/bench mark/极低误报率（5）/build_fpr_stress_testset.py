"""
极低误报率 —— 第一步：构造误报压力测试集

从原始测试数据中专门挑选 true_label == "non_rumor" 的真实新闻，
特别偏好那些"看起来很像谣言"的真新闻（包含敏感词、感叹号、
惊悚表述等），用来极限测试模型的误报率。

同时从全量数据补充一批"易诱发误报"的合成样本，
模拟真实场景中最容易被误伤的正常内容。

用法:
    python3 build_fpr_stress_testset.py
    python3 build_fpr_stress_testset.py --sample 150

输出:
    误报压力测试集.json     —— 全部标签为 non_rumor 的压力数据
    误报压力测试集_统计.txt  —— 统计报告
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
    "..", "原测试集", "Combined_Shuffled_Dataset_V_Augmented.json"
)
OUTPUT_JSON = "误报压力测试集.json"
OUTPUT_STATS = "误报压力测试集_统计.txt"
DEFAULT_SAMPLE = 150
RANDOM_SEED = 42

SENSITIVE_PATTERNS = [
    r"爆炸|爆发|死亡|死了|身亡|遇难",
    r"地震|台风|洪水|灾难|灾害|泥石流",
    r"火灾|起火|燃烧|坍塌|倒塌|垮塌",
    r"病毒|疫情|感染|确诊|肺炎|传染",
    r"枪击|shooting|killed|attack|bomb|terror",
    r"crash|explosion|dead|death|die|murder",
    r"紧急|突发|最新|重磅|速看|刚刚",
    r"警方|警告|通报|处罚|抓获|逮捕",
    r"有毒|致癌|辐射|污染|危害|危险",
    r"失踪|绑架|诈骗|骗局|曝光|内幕",
    r"震惊|可怕|恐怖|惊人|太吓人|不敢相信",
    r"breaking|urgent|alert|warning|emergency",
]

SYNTHETIC_NON_RUMORS = [
    {"text": "【突发】今晨6时，四川雅安发生4.2级地震，震源深度15公里。据中国地震台网正式测定，暂无人员伤亡报告。", "true_label": "non_rumor", "category": "灾难新闻"},
    {"text": "紧急通知！因暴雨预警，明日全市中小学停课一天，请各位家长做好安排。——市教育局", "true_label": "non_rumor", "category": "官方通知"},
    {"text": "重磅！国务院发布最新政策：2024年起个税起征点调整为6000元。", "true_label": "non_rumor", "category": "政策新闻"},
    {"text": "警方通报：昨日网传的'某小区绑架儿童'一事，经查系家庭纠纷，并非绑架案件。", "true_label": "non_rumor", "category": "警方通报"},
    {"text": "刚刚，SpaceX星舰第五次试飞成功！助推器首次实现空中回收，马斯克称这是人类航天的里程碑！", "true_label": "non_rumor", "category": "科技新闻"},
    {"text": "【速看】暴雨橙色预警！今明两天广东多地将出现大到暴雨，局部特大暴雨，请注意防范。——广东省气象台", "true_label": "non_rumor", "category": "气象预警"},
    {"text": "惊人发现！中国科学家在月球土壤中首次检测到新矿物'嫦娥石'，这是人类发现的第六种月球新矿物。", "true_label": "non_rumor", "category": "科学发现"},
    {"text": "太可怕了！今天亲眼看到一辆大货车在高速上侧翻，消防救援人员已经到场，司机已被救出送医。", "true_label": "non_rumor", "category": "亲历事件"},
    {"text": "央视曝光：某品牌儿童玩具重金属超标，涉及产品已被市场监管部门责令下架召回。", "true_label": "non_rumor", "category": "曝光报道"},
    {"text": "震惊！高考状元竟然来自一个贫困县的乡村中学，她的故事令无数人动容。", "true_label": "non_rumor", "category": "煽情标题"},
    {"text": "breaking: magnitude 6.1 earthquake strikes off the coast of japan. tsunami warning issued for coastal areas. no casualties reported yet.", "true_label": "non_rumor", "category": "英文突发"},
    {"text": "urgent: severe thunderstorm warning for the greater london area. residents advised to stay indoors. public transport may be affected.", "true_label": "non_rumor", "category": "英文预警"},
    {"text": "5 people confirmed dead after building collapse in mumbai. rescue operations ongoing. pm modi expresses condolences.", "true_label": "non_rumor", "category": "英文灾难"},
    {"text": "最新！某市出现1例猴痘确诊病例，患者已隔离治疗，密接人员已全部追踪管控。——市卫健委", "true_label": "non_rumor", "category": "疫情通报"},
    {"text": "不敢相信！一条藏獒的价格竟然降到了几百块，曾经炒到上千万的天价犬如今无人问津。", "true_label": "non_rumor", "category": "夸张真事"},
]


def has_sensitive_content(text: str) -> bool:
    """检测文本是否包含容易诱发误报的敏感词"""
    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def strip_social_signals(text: str) -> str:
    """清洗社交信号（复用指标一的逻辑）"""
    text = re.sub(r"@[\w\u4e00-\u9fff]+", "", text)
    text = re.sub(r"<\s*(?:url|@user|link|img|pic)\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"#[^#\s]+#?", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    import argparse
    parser = argparse.ArgumentParser(description="构造误报压力测试集")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help=f"抽样数量 (默认 {DEFAULT_SAMPLE})")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_path = os.path.abspath(SOURCE_FILE)

    if not os.path.exists(source_path):
        print(f"❌ 源数据不存在: {source_path}")
        sys.exit(1)

    with open(source_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    print(f"📂 读取源数据: {len(raw_data)} 条")

    non_rumors = []
    for item in raw_data:
        if item.get("output", "").strip() == "No":
            text = strip_social_signals(item.get("input", ""))
            if len(text) >= 10:
                non_rumors.append({
                    "text": text,
                    "true_label": "non_rumor",
                    "has_sensitive": has_sensitive_content(text),
                })

    print(f"   非谣言样本: {len(non_rumors)} 条")

    sensitive_pool = [r for r in non_rumors if r["has_sensitive"]]
    normal_pool = [r for r in non_rumors if not r["has_sensitive"]]
    print(f"   其中含敏感词: {len(sensitive_pool)} 条")

    random.seed(RANDOM_SEED)

    n_synthetic = len(SYNTHETIC_NON_RUMORS)
    n_from_data = args.sample - n_synthetic
    n_sensitive = min(len(sensitive_pool), int(n_from_data * 0.6))
    n_normal = n_from_data - n_sensitive

    selected = []
    selected.extend(random.sample(sensitive_pool, min(n_sensitive, len(sensitive_pool))))
    selected.extend(random.sample(normal_pool, min(n_normal, len(normal_pool))))

    for item in SYNTHETIC_NON_RUMORS:
        selected.append({
            "text": item["text"],
            "true_label": item["true_label"],
            "has_sensitive": True,
            "category": item.get("category", "合成样本"),
        })

    random.shuffle(selected)

    for i, item in enumerate(selected):
        item["index"] = i

    output_path = os.path.join(script_dir, OUTPUT_JSON)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)

    total = len(selected)
    sensitive_count = sum(1 for s in selected if s.get("has_sensitive"))
    synthetic_count = sum(1 for s in selected if s.get("category"))

    stats_lines = [
        "=" * 55,
        "  误报压力测试集 构建报告",
        "=" * 55,
        f"  总样本数:         {total}",
        f"  全部标签:         non_rumor (真实新闻)",
        f"  含敏感词样本:     {sensitive_count} ({sensitive_count/total*100:.1f}%)",
        f"  合成高压样本:     {synthetic_count}",
        f"  来自原数据集:     {total - synthetic_count}",
        "-" * 55,
        "  设计意图:",
        "    所有样本均为真实的非谣言内容，但其中大量包含",
        "    敏感词汇（爆炸、死亡、紧急等），故意诱导模型",
        "    产生误报。误报率 = 被错判为 rumor 的比例。",
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
