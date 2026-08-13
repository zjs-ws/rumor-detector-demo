# 对抗扰动抵抗度 (Adversarial Text Resilience) 评测完整指南

## 一、这个指标在证明什么

真实世界的造谣者非常狡猾——谐音梗、拼音缩写、错别字、符号穿插（"辽 宁 爆 发 H-7-N-9"）都是常规操作。传统 TF-IDF/词袋模型遇到这些"脏数据"直接瘫痪。

本指标证明：**Agent 具备强大的上下文纠错能力，即使文本被严重扰动，依然能识破谣言，而基线模型会出现显著的性能暴跌。**

核心对比逻辑：

```
               纯净数据        对抗数据        跌幅
Agent:          86.5%    →      83.0%       仅跌 3.5pp   ← 抗干扰强
裸 LLM:         74.0%    →      58.5%       暴跌 15.5pp  ← 被干扰打崩
```

---

## 二、环境准备

```bash
pip install requests openai
export DASHSCOPE_API_KEY="sk-你的key"     # 基线评测需要
```

---

## 三、完整操作流程

### Step 1：构造对抗性脏数据

从指标一的纯净测试集出发，自动施加 6 类扰动：

| 扰动类型 | 示例 | 干扰效果 |
|---------|------|---------|
| 谐音替换 | "政府" → "正付" | 破坏分词 |
| 字符穿插 | "爆发" → "爆 发" | 切断词语边界 |
| 视觉混淆 | "people" → "pe0p1e" | 干扰英文识别 |
| 数字穿插 | "H7N9" → "H-7-N-9" | 破坏实体识别 |
| emoji 干扰 | "紧急 🔥 通知 ⚠️" | 增加噪声 |
| 繁简混排 | "国家发布" → "國家發布" | 字符集混乱 |

```bash
cd /Users/wangsheng/Desktop/数据集/对抗扰动抵抗度（4）

# 中等强度（默认，推荐）
python3 build_adversarial_testset.py

# 轻度（只做少量扰动）
python3 build_adversarial_testset.py --intensity light

# 重度（大量扰动，极端压力测试）
python3 build_adversarial_testset.py --intensity heavy
```

输出 `对抗测试集.json` 和 `对抗测试集_统计.txt`，统计报告会展示扰动前后的对比示例。

---

### Step 2：在脏数据上评测 Agent

```bash
# 先测 5 条验证
python3 evaluate_adversarial.py agent --limit 5

# 跑全部
python3 evaluate_adversarial.py agent

# 指定接口地址
python3 evaluate_adversarial.py agent --api http://你的IP:端口/detect
```

输出 `Agent_对抗评测报告.txt` 和 `Agent_对抗评测结果.json`。

---

### Step 3：在脏数据上评测基线

```bash
# 先测 5 条
python3 evaluate_adversarial.py baseline --limit 5

# 跑全部
python3 evaluate_adversarial.py baseline

# 换模型
python3 evaluate_adversarial.py baseline --model qwen-turbo
```

输出 `基线_对抗评测报告.txt` 和 `基线_对抗评测结果.json`。

---

### Step 4：对比跌幅

```bash
python3 compare_degradation.py
```

脚本自动读取 4 份数据（指标一的纯净结果 + 本指标的对抗结果），计算跌幅对比：

```
  ┌──────────────────────────────────────────────────┐
  │       方法    纯净数据    对抗数据      跌幅     │
  ├──────────────────────────────────────────────────┤
  │      Agent     86.5%      83.0%     -3.5%     │
  │     裸 LLM     74.0%      58.5%    -15.5%     │
  └──────────────────────────────────────────────────┘

  Agent 抗干扰优势: 12.0%
```

报告还自动生成结题答辩话术。

---

## 四、三档扰动强度说明

| 参数 | 谐音概率 | 穿插概率 | 视觉混淆 | emoji | 繁简 | 适用场景 |
|------|---------|---------|---------|-------|------|---------|
| `light` | 15% | 8% | 10% | 5% | 10% | 温和测试 |
| `medium` | 30% | 15% | 20% | 10% | 20% | 推荐，平衡 |
| `heavy` | 50% | 25% | 35% | 15% | 30% | 极端压力 |

推荐先用 `medium` 跑出主要数据，如果 Agent 和基线差距不大再加 `heavy`。

---

## 五、答辩呈现建议

**柱状图（强推）**：纯净 vs 对抗的准确率双柱对比，Agent 和基线各一组，视觉冲击力极强。

**表格**：

```
╔════════════════════╦══════════╦══════════╦════════╗
║ 方法                ║ 纯净数据  ║ 对抗数据  ║ 跌幅   ║
╠════════════════════╬══════════╬══════════╬════════╣
║ 裸 LLM (qwen-plus) ║  xx.x%   ║  xx.x%   ║ -xx.x% ║
║ 我们的 Agent        ║  xx.x%   ║  xx.x%   ║ -x.x%  ║
╠════════════════════╬══════════╬══════════╬════════╣
║ Agent 抗干扰优势    ║          ║          ║ xx.x%  ║
╚════════════════════╩══════════╩══════════╩════════╝
```

---

## 六、常见问题

### Q1: 对抗测试集里有的文本完全没变

正常。扰动是概率性的，部分短文本或全英文文本可能没有触发任何规则。统计报告会显示实际被扰动的比例。

### Q2: 想自定义谐音词典

编辑 `build_adversarial_testset.py` 中的 `HOMOPHONE_MAP_ZH` 字典，加入你们领域的谐音词即可。

### Q3: 对比报告提示"部分数据缺失"

需要 4 份数据都齐全：指标一的 Agent/基线纯净结果 + 本指标的 Agent/基线对抗结果。按顺序把没跑完的补上即可。

---

## 七、完整命令速查

```bash
cd /Users/wangsheng/Desktop/数据集/对抗扰动抵抗度（4）

# Step 1: 构造脏数据
python3 build_adversarial_testset.py

# Step 2: 评测 Agent
python3 evaluate_adversarial.py agent

# Step 3: 评测基线
export DASHSCOPE_API_KEY="sk-你的key"
python3 evaluate_adversarial.py baseline

# Step 4: 对比跌幅
python3 compare_degradation.py
```
