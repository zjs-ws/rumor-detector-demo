# 解释质量与多维自洽度 (Justification Quality) 评测完整指南

## 一、这个指标在证明什么

评委看到 Agent 的雷达图，第一反应一定是："这些分是怎么来的，是不是瞎画的？"

本指标从两个角度回应这个质疑：

| 量化条件 | 方法 | 证明什么 |
|---------|------|---------|
| **自洽度** | 脚本自动检测打分与 reason 字段的一致性 | 每根轴都有据可查，高分必有对应论据 |
| **解释质量** | A/B 盲测，让真人在不知出处的情况下选择更信服的报告 | 人类主观认可度压倒基线 |

---

## 二、完整操作流程

### 量化条件 1：打分-解释自洽度（自动化）

#### 原理

脚本检查 Agent 返回的 JSON 中每个维度的打分和 reason 文本是否一致。例如：
- "情绪煽动"打了 90 分 -> reason 里**必须**能找到"感叹号""夸张""煽动"等关键词
- 如果打了高分却没有任何相关论据 -> 记为"不自洽"

#### 运行

```bash
cd /Users/wangsheng/Desktop/数据集/解释质量与自洽度（3）

# 指定 Agent 输出文件
python3 check_consistency.py --input /path/to/agent_results.json

# 调整高分阈值（默认 70）
python3 check_consistency.py --input agent_results.json --threshold 60
```

#### Agent 返回格式要求

脚本自动识别以下格式，优先使用 `scores` 字段：

```json
{
    "text": "某条待检测文本",
    "predicted_label": "rumor",
    "scores": {
        "情绪煽动": 90,
        "逻辑漏洞": 75,
        "事实偏差": 85,
        "来源可疑": 60,
        "时效过期": 30
    },
    "reason": "该文本使用了大量感叹号和夸张表述，具有明显的情绪煽动特征..."
}
```

也兼容 `dimensions`、`radar` 等字段名，或仅有 `risk_score` 的简化格式。

#### 已配置的维度关键词

| 维度 | 检测关键词（部分） |
|------|-----------------|
| 情绪煽动 | 感叹号、夸张、煽动、耸人听闻、紧急、恐慌 |
| 逻辑漏洞 | 逻辑、矛盾、以偏概全、偷换概念、论据不足 |
| 事实偏差 | 事实、核实、不实、篡改、失真 |
| 来源可疑 | 来源、匿名、未经证实、传闻、不可靠 |
| 时效过期 | 过期、旧闻、翻炒、已辟谣、时效 |
| 传播异常 | 传播、水军、异常增长、短时间大量 |

如果你们的雷达图有其他维度，只需在 `check_consistency.py` 的 `DIMENSION_KEYWORDS` 字典中添加对应的正则模式即可。

#### 输出

| 文件 | 内容 |
|------|------|
| `自洽性检测报告.txt` | 样本级/维度级自洽率、各维度明细、不自洽案例 |
| `自洽性逐条结果.json` | 每条每个维度的检测详情 |

---

### 量化条件 2：A/B 盲测（人工评估）

分三步走：**生成问卷 -> 投票 -> 统计**。

#### Step 1: 生成盲测问卷

```bash
python3 abtest_blind_eval.py generate \
    --agent /path/to/agent_results.json \
    --baseline /path/to/baseline_results.json \
    --sample 30
```

脚本会：
- 将 Agent 和基线的辟谣理由按原帖配对
- **随机打乱 A/B 位置**（有的题 Agent 是 A，有的是 B），防止位置偏见
- 输出 `盲测问卷.json`

#### Step 2: 投票（二选一）

**方式 A：终端交互式（个人）**

```bash
python3 abtest_blind_eval.py evaluate
```

逐题展示原帖 + 两份报告，输入 a/b/t 投票：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [1/30] 原帖:
    震惊！某大学食堂用地沟油被曝光...

  ┌── 报告 A ──
  │ 该信息为谣言。经查证该校后勤处于2024年3月发布声明...
  └──────────

  ┌── 报告 B ──
  │ No
  └──────────

  你更信服哪份？[a / b / t(平手) / q(退出)]:
```

可多人依次运行，投票结果自动累加。

**方式 B：导出 CSV 发给多人**

```bash
# 导出
python3 abtest_blind_eval.py evaluate --export-csv

# 把 盲测问卷模板.csv 发给 10 个同学
# 他们在 Excel 中填写 a/b/t 后把文件回传
```

#### Step 3: 统计胜率

```bash
# 只用终端投票的数据
python3 abtest_blind_eval.py stats

# 合并 CSV 回传的投票
python3 abtest_blind_eval.py stats --import-csv 同学1.csv 同学2.csv 同学3.csv
```

输出报告示例：

```
============================================================
    解释质量 · A/B 盲测胜率报告
============================================================
  评测人数:          10
  总投票数:          300

  ┌─────────────────────────────────────────────┐
  │  Agent 胜出:       246 次  (87.2%)           │
  │  基线 胜出:         36 次  (12.8%)           │
  │  平手:              18 次                    │
  │                                               │
  │  结论:    Agent 压倒性胜出                     │
  └─────────────────────────────────────────────┘
```

#### 输出

| 文件 | 内容 |
|------|------|
| `盲测问卷.json` | 配对好的题目（含隐藏的来源标记） |
| `盲测投票结果.json` | 所有投票原始数据 |
| `盲测胜率报告.txt` | 胜率、各评测人投票分布 |

---

### 汇总：综合报告

两个量化条件都跑完后：

```bash
python3 calculate_justification.py
```

生成 `解释质量与自洽度_综合报告.txt`，同时包含自洽率和盲测胜率，以及结题话术参考。

---

## 三、答辩呈现建议

**推荐表格**：

```
╔══════════════════════╦════════════════════════════════════╗
║ 量化条件              ║ 结果                               ║
╠══════════════════════╬════════════════════════════════════╣
║ 打分-解释自洽率       ║ xx.x% (xx/xx 个维度检测通过)        ║
║ A/B 盲测 Agent 胜率   ║ xx.x% (N人参与, 压倒性胜出)        ║
╚══════════════════════╩════════════════════════════════════╝
```

**话术参考**：

> "我们从两个角度证明雷达图的可靠性：第一，自动化自洽性检测显示
> xx.x% 的维度打分在 reason 中有对应论据支撑；第二，在 N 人参与的
> A/B 盲测中，隐去来源标识后，评测者以 xx.x% 的压倒性胜率选择了
> 我们 Agent 的辟谣报告。"

---

## 四、常见问题

### Q1: Agent 没有多维打分字段

如果你们的 Agent 接口只返回 `risk_score` 而没有 `scores` 字典，`check_consistency.py` 会退化为只检测综合风险分与 reason 的一致性。建议在 Agent 端增加多维打分输出。

### Q2: 基线没有 reason 字段

基线评测（裸 LLM）的 `raw_output` 通常只是 "Yes"/"No"，没有解释。这恰恰是盲测的优势——评测者会看到：

- 报告 A：一份详细的多维分析
- 报告 B：一个孤零零的 "Yes"

Agent 的胜率会非常高，这正好证明了解释质量的差距。

### Q3: 想增加/修改雷达图维度

编辑 `check_consistency.py` 中的 `DIMENSION_KEYWORDS` 字典，添加你们自定义维度和对应的检测关键词即可。

### Q4: 盲测人数太少，结果有说服力吗

大创结题 10 人左右足够。如果只有 3-5 人，确保每人至少做 20-30 题，让总投票数达到 100+ 即可。

---

## 五、完整命令速查

```bash
cd /Users/wangsheng/Desktop/数据集/解释质量与自洽度（3）

# ===== 量化条件 1: 自洽度 =====
python3 check_consistency.py --input /path/to/agent_results.json

# ===== 量化条件 2: A/B 盲测 =====
# 生成问卷
python3 abtest_blind_eval.py generate \
    --agent /path/to/agent_results.json \
    --baseline /path/to/baseline_results.json

# 投票（终端交互）
python3 abtest_blind_eval.py evaluate

# 或导出 CSV
python3 abtest_blind_eval.py evaluate --export-csv

# 统计胜率
python3 abtest_blind_eval.py stats
python3 abtest_blind_eval.py stats --import-csv *.csv

# ===== 汇总报告 =====
python3 calculate_justification.py
```
