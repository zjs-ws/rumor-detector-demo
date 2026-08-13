"""
极低误报率 —— 核心评测脚本

对「误报压力测试集」（全部标签为 non_rumor 的高压样本）
分别调用 Agent 和基线 LLM 进行判别，
计算误报率 (FPR) 并生成逐条误报案例分析。

用法:
    # 评测 Agent
    python3 evaluate_false_positive.py --target agent --api http://127.0.0.1:8000/detect

    # 评测基线 LLM
    export DASHSCOPE_API_KEY="sk-xxxxxxxx"
    python3 evaluate_false_positive.py --target baseline

    # 先跑 10 条验证连通性
    python3 evaluate_false_positive.py --target agent --limit 10

输出:
    Agent_误报评测结果.json   / Agent_误报评测报告.txt
    基线_误报评测结果.json    / 基线_误报评测报告.txt
"""

import json
import re
import time
import argparse
import os
import sys
from collections import defaultdict

try:
    import requests
except ImportError:
    requests = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ======================== 配置 ========================
DEFAULT_API_URL = "http://127.0.0.1:8000/detect"
DEFAULT_MODEL = "qwen-plus"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
REQUEST_TIMEOUT = 60
RETRY_LIMIT = 3
RETRY_DELAY = 2
RATE_LIMIT_DELAY = 0.5

TESTSET_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "误报压力测试集.json"
)

SENSITIVE_PATTERNS = [
    (r"爆炸|爆发", "爆炸/爆发"),
    (r"死亡|死了|身亡|遇难", "死亡类"),
    (r"地震|台风|洪水|灾难|灾害|泥石流", "自然灾害"),
    (r"火灾|起火|燃烧|坍塌|倒塌|垮塌", "火灾/坍塌"),
    (r"病毒|疫情|感染|确诊|肺炎|传染", "疫情类"),
    (r"枪击|shooting|killed|attack|bomb|terror", "暴力/恐怖"),
    (r"crash|explosion|dead|death|die|murder", "英文暴力"),
    (r"紧急|突发|最新|重磅|速看|刚刚", "紧急标签"),
    (r"警方|警告|通报|处罚|抓获|逮捕", "执法类"),
    (r"有毒|致癌|辐射|污染|危害|危险", "健康危害"),
    (r"失踪|绑架|诈骗|骗局|曝光|内幕", "犯罪/曝光"),
    (r"震惊|可怕|恐怖|惊人|太吓人|不敢相信", "情绪煽动"),
    (r"breaking|urgent|alert|warning|emergency", "英文紧急"),
]

LABEL_NORMALIZE = {
    "yes": "rumor", "no": "non_rumor", "unknown": "unknown",
    "rumor": "rumor", "non_rumor": "non_rumor", "non-rumor": "non_rumor",
    "not rumor": "non_rumor", "真实": "non_rumor", "谣言": "rumor",
    "不是谣言": "non_rumor", "未知": "unknown", "是": "rumor", "否": "non_rumor",
}

SYSTEM_PROMPT = (
    "判断以下文本是否为谣言。"
    "你必须严格只输出以下三个选项之一：Yes、No、Unknown。"
    "不要输出任何其他内容。"
)


# ======================== 敏感词分析 ========================

def detect_trigger_words(text: str) -> list[str]:
    """识别文本中命中了哪些敏感词类别"""
    triggers = []
    for pattern, category in SENSITIVE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            triggers.append(category)
    return triggers


# ======================== Agent 调用 ========================

def parse_agent_response(response_json: dict) -> dict:
    conclusion = (
        response_json.get("conclusion")
        or response_json.get("result")
        or response_json.get("label")
        or response_json.get("output")
        or response_json.get("prediction")
        or ""
    )
    conclusion = LABEL_NORMALIZE.get(conclusion.strip().lower(), conclusion.strip().lower())
    risk_score = response_json.get("risk_score", response_json.get("score", None))
    if risk_score is not None:
        risk_score = float(risk_score)
    reason = response_json.get("reason", response_json.get("explanation", ""))
    return {"predicted_label": conclusion, "risk_score": risk_score, "reason": reason}


def call_agent(text: str, api_url: str) -> dict:
    if requests is None:
        print("❌ 缺少 requests 库: pip install requests")
        sys.exit(1)
    resp = requests.post(api_url, json={"text": text}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ======================== 基线 LLM 调用 ========================

def init_qwen_client() -> "OpenAI":
    if OpenAI is None:
        print("❌ 缺少 openai 库: pip install openai")
        sys.exit(1)
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY 环境变量")
        sys.exit(1)
    return OpenAI(api_key=api_key, base_url=QWEN_BASE_URL)


def baseline_predict(client, text: str, model: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        max_tokens=10,
    )
    return resp.choices[0].message.content.strip()


def normalize_prediction(raw_output: str) -> str:
    cleaned = raw_output.strip().strip("'\".,。，").lower()
    exact = LABEL_NORMALIZE.get(cleaned)
    if exact:
        return exact
    for keyword, label in [
        ("yes", "rumor"), ("no", "non_rumor"), ("unknown", "unknown"),
        ("谣言", "rumor"), ("不是", "non_rumor"), ("真实", "non_rumor"),
        ("未知", "unknown"), ("无法判断", "unknown"),
    ]:
        if keyword in cleaned:
            return label
    return cleaned


# ======================== 指标计算 ========================

def compute_fpr_metrics(results: list[dict]) -> dict:
    """
    核心指标：误报率 (False Positive Rate)
    因为测试集全部标签为 non_rumor，所以:
        FPR = 被预测为 rumor 的数量 / 总数量
    """
    total = len(results)
    false_positives = [r for r in results if r["predicted_label"] == "rumor"]
    marked_unknown = [r for r in results if r["predicted_label"] == "unknown"]
    correct = [r for r in results if r["predicted_label"] == "non_rumor"]

    fpr = len(false_positives) / total if total else 0.0
    accuracy = len(correct) / total if total else 0.0
    unknown_rate = len(marked_unknown) / total if total else 0.0

    trigger_stats = defaultdict(lambda: {"total": 0, "false_positive": 0})
    for r in results:
        for cat in r.get("trigger_categories", []):
            trigger_stats[cat]["total"] += 1
            if r["predicted_label"] == "rumor":
                trigger_stats[cat]["false_positive"] += 1

    for cat in trigger_stats:
        t = trigger_stats[cat]["total"]
        fp = trigger_stats[cat]["false_positive"]
        trigger_stats[cat]["fpr"] = fp / t if t else 0.0

    trigger_stats = dict(sorted(trigger_stats.items(), key=lambda x: x[1]["fpr"], reverse=True))

    return {
        "total": total,
        "false_positives": len(false_positives),
        "correct": len(correct),
        "unknown": len(marked_unknown),
        "fpr": fpr,
        "accuracy": accuracy,
        "unknown_rate": unknown_rate,
        "trigger_category_stats": {k: dict(v) for k, v in trigger_stats.items()},
        "fp_cases": [
            {
                "index": r["index"],
                "text": r["text"][:80],
                "trigger_categories": r.get("trigger_categories", []),
                "reason": r.get("reason", ""),
            }
            for r in false_positives
        ],
    }


def format_fpr_report(metrics: dict, elapsed: float, method_name: str) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"    误报率 (FPR) 专项评估报告 —— {method_name}")
    lines.append("=" * 60)
    lines.append(f"  方法:              {method_name}")
    lines.append(f"  测试集:            误报压力测试集（全部 non_rumor）")
    lines.append(f"  总样本数:          {metrics['total']}")
    lines.append(f"  正确判为非谣言:    {metrics['correct']} ({metrics['accuracy']:.1%})")
    lines.append(f"  错判为谣言:        {metrics['false_positives']} (误报)")
    lines.append(f"  判为未知:          {metrics['unknown']} ({metrics['unknown_rate']:.1%})")
    lines.append("")
    lines.append(f"  ★ 误报率 (FPR):   {metrics['fpr']:.2%}")
    lines.append(f"  ★ 准确率:         {metrics['accuracy']:.2%}")
    lines.append(f"  总耗时:            {elapsed:.1f}s")
    lines.append(f"  平均每条耗时:      {elapsed / metrics['total']:.2f}s")
    lines.append("")

    trigger_stats = metrics.get("trigger_category_stats", {})
    if trigger_stats:
        lines.append("-" * 60)
        lines.append("  各敏感词类别的误报率 (用于定位薄弱点):")
        lines.append(f"  {'敏感类别':>12s}  {'该类样本':>8s}  {'误报':>4s}  {'类内FPR':>8s}")
        lines.append("  " + "-" * 44)
        for cat, info in trigger_stats.items():
            lines.append(
                f"  {cat:>12s}  {info['total']:>8d}  {info['false_positive']:>4d}  {info['fpr']:>8.1%}"
            )
        lines.append("")

    fp_cases = metrics.get("fp_cases", [])
    if fp_cases:
        lines.append("-" * 60)
        lines.append(f"  误报案例列表 (共 {len(fp_cases)} 条):")
        for i, case in enumerate(fp_cases[:20]):
            lines.append(f"  [{i+1}] 文本: {case['text']}")
            lines.append(f"       敏感类别: {', '.join(case['trigger_categories']) or '无'}")
            if case.get("reason"):
                lines.append(f"       模型理由: {str(case['reason'])[:80]}")
            lines.append("")
        if len(fp_cases) > 20:
            lines.append(f"  ... 还有 {len(fp_cases) - 20} 条，详见 JSON 文件")
            lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(description="误报率 (FPR) 专项评测")
    parser.add_argument("--target", choices=["agent", "baseline"], required=True,
                        help="评测对象: agent 或 baseline")
    parser.add_argument("--api", default=DEFAULT_API_URL, help="Agent 接口地址")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"基线 LLM 模型 (默认 {DEFAULT_MODEL})")
    parser.add_argument("--testset", default=TESTSET_FILE, help="测试集 JSON")
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 条 (0=全部)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    testset_path = os.path.abspath(args.testset)

    if not os.path.exists(testset_path):
        print(f"❌ 测试集不存在: {testset_path}")
        print("   请先运行: python3 build_fpr_stress_testset.py")
        sys.exit(1)

    with open(testset_path, "r", encoding="utf-8") as f:
        test_data = json.load(f)
    if args.limit > 0:
        test_data = test_data[:args.limit]

    is_agent = args.target == "agent"
    method_name = "Agent 智能体" if is_agent else f"基线 LLM ({args.model})"
    prefix = "Agent" if is_agent else "基线"

    client = None
    if not is_agent:
        client = init_qwen_client()

    print(f"📋 测试集已加载: {len(test_data)} 条 (全部 non_rumor)")
    print(f"🎯 评测对象: {method_name}")
    print("=" * 50)

    results = []
    errors = []
    t_start = time.time()

    for idx, item in enumerate(test_data):
        text = item["text"]
        trigger_cats = detect_trigger_words(text)
        display_text = text[:40] + ("..." if len(text) > 40 else "")

        predicted_label = None
        reason = ""
        risk_score = None

        if is_agent:
            try:
                raw_resp = call_agent(text, args.api)
                parsed = parse_agent_response(raw_resp)
                predicted_label = parsed["predicted_label"]
                reason = parsed["reason"]
                risk_score = parsed["risk_score"]
            except Exception as e:
                print(f"  [{idx+1:3d}/{len(test_data)}] 🔴 异常: {e}")
                errors.append({"index": idx, "text": text, "error": str(e)})
                continue
        else:
            raw_output = None
            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    raw_output = baseline_predict(client, text, args.model)
                    break
                except Exception as e:
                    if "rate" in str(e).lower() or "429" in str(e):
                        time.sleep(RETRY_DELAY * attempt)
                    elif attempt == RETRY_LIMIT:
                        print(f"  [{idx+1:3d}/{len(test_data)}] 🔴 失败: {e}")
                        errors.append({"index": idx, "text": text, "error": str(e)})
                    else:
                        time.sleep(RETRY_DELAY)
            if raw_output is None:
                continue
            predicted_label = normalize_prediction(raw_output)
            reason = raw_output

        is_fp = predicted_label == "rumor"
        status = "❌ 误报!" if is_fp else ("⚠️ 未知" if predicted_label == "unknown" else "✅")

        record = {
            "index": idx,
            "text": text,
            "true_label": "non_rumor",
            "predicted_label": predicted_label,
            "risk_score": risk_score,
            "reason": reason,
            "is_false_positive": is_fp,
            "trigger_categories": trigger_cats,
        }
        results.append(record)

        print(f"  [{idx+1:3d}/{len(test_data)}] {status} 预测={predicted_label:10s}  触发={trigger_cats}  {display_text}")

        if not is_agent:
            time.sleep(RATE_LIMIT_DELAY)

    elapsed = time.time() - t_start
    print(f"\n{'=' * 50}")

    if not results:
        print("❌ 无有效结果")
        sys.exit(1)

    metrics = compute_fpr_metrics(results)
    report = format_fpr_report(metrics, elapsed, method_name)
    print(report)

    report_path = os.path.join(script_dir, f"{prefix}_误报评测报告.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"📄 报告已保存: {report_path}")

    detail_path = os.path.join(script_dir, f"{prefix}_误报评测结果.json")
    detail_output = {
        "config": {"target": args.target, "method": method_name},
        "metrics_summary": metrics,
        "results": results,
        "errors": errors,
    }
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 逐条结果已保存: {detail_path}")

    if errors:
        print(f"\n⚠️  共 {len(errors)} 条请求失败，详见结果文件")


if __name__ == "__main__":
    main()
