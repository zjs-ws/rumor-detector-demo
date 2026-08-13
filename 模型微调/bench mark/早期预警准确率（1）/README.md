# 早期预警准确率 (Early Detection Accuracy) 评测完整指南

## 一、这个指标在证明什么

传统谣言检测方法需要依赖评论、转发树、用户画像等**传播链数据**才能判断——这意味着它们必须"等子弹飞一会儿"。

本评测的核心目标：**向评委证明我们的 Agent 在只拿到一条孤零零的原帖（零评论、零转发、零传播数据）时，就能精准识破谣言。**

评测设计了两组实验，跑在同一份数据上进行公平对比：

| 实验组 | 方法 | 证明什么 |
|-------|------|---------|
| Agent 评测 | 我们的完整 Agent（推理链 + 知识检索 + 多步验证） | 早期预警的实际能力 |
| 基线 1 | 裸 LLM 直接 Prompting（同一个底座模型，但不走 Agent 流程） | Agent 架构的增益不是大模型本身的功劳 |

---

## 二、环境准备

### 2.1 Python 版本

Python 3.9 及以上均可。

### 2.2 安装依赖

```bash
pip install requests openai
```

- `requests`：Agent 评测脚本用来向你们的 FastAPI 接口发送 HTTP 请求
- `openai`：基线评测脚本用来调用通义千问 API（走 OpenAI 兼容协议）

### 2.3 通义千问 API Key（基线评测需要）

1. 打开 [DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 登录后进入「API-KEY 管理」，创建一个 Key
3. 在终端设置环境变量：

```bash
export DASHSCOPE_API_KEY="sk-你的key"
```

> Agent 评测不需要这个 Key，它直接调用你们自己的 FastAPI 接口。

---

## 三、完整操作流程

### Step 1：构建纯文本测试集（已完成，一般无需重跑）

**目的**：从 1940 条原始测试数据中，随机抽取 200 条，物理切断所有传播链信号，只保留裸文本。

```bash
cd /Users/wangsheng/Desktop/数据集/早期预警准确率
python3 build_early_warning_testset.py
```

**数据清洗细节**（脚本自动完成）：

| 清洗项 | 示例 | 处理方式 |
|-------|------|---------|
| @用户提及 | `@张三` `@CNN` | 删除 |
| URL 链接 | `http://t.cn/xxx` | 删除 |
| 占位符标记 | `<url>` `<@user>` | 删除 |
| 话题标签 | `#谣言#` `#breaking` | 删除 |
| 转发标记 | `转发微博` `[转]` | 删除 |
| 过短文本 | 少于 4 个字符 | 整条跳过 |

**产物**：

- `早期预警测试集.json` — 200 条，每条只有 `{"text": "...", "true_label": "rumor/non_rumor/unknown"}`
- `早期预警测试集_统计.txt` — 标签分布：rumor 78 条 / non_rumor 75 条 / unknown 47 条

> 两组实验共用这同一份测试集，保证对比公平。

---

### Step 2：跑 Agent 评测（实验组）

#### 2.1 先启动你们的 Agent 服务

确保你们的 Agent FastAPI 服务正在运行。假设启动方式是：

```bash
# 在你们的 Agent 项目目录下
uvicorn main:app --host 0.0.0.0 --port 8000
```

#### 2.2 确认接口能通

手动发一条请求验证连通性：

```bash
curl -X POST http://127.0.0.1:8000/detect \
     -H "Content-Type: application/json" \
     -d '{"text": "内部消息，明天起早操出勤率直接与挂科挂钩！"}'
```

你应该看到类似这样的 JSON 返回：

```json
{"conclusion": "rumor", "risk_score": 0.92, "reason": "该信息缺乏官方来源..."}
```

#### 2.3 跑评测

```bash
cd /Users/wangsheng/Desktop/数据集/早期预警准确率/Agent评测

# 先测 5 条，确认流程能跑通
python3 evaluate_early_warning.py --limit 5

# 确认没问题后，跑全部 200 条
python3 evaluate_early_warning.py

# 如果 Agent 不在本机或端口不同，用 --api 指定
python3 evaluate_early_warning.py --api http://192.168.1.100:9000/detect
```

**运行过程中你会看到**：

```
📋 测试集已加载: 200 条记录
🌐 目标接口: http://127.0.0.1:8000/detect
📌 方法: Agent 智能体（完整架构）
==================================================
  [  1/200] ✅ 真实=non_rumor   预测=non_rumor    white house is aglow in the colors...
  [  2/200] ❌ 真实=unknown     预测=rumor         nurses save lives of all differen...
  [  3/200] ✅ 真实=rumor       预测=rumor         first photo from the malaysia air...
  ...
```

**完成后自动生成**：

| 文件 | 内容 |
|------|------|
| `Agent评测/早期预警评估报告.txt` | 总体准确率、分类别准确率、Precision/Recall/F1、混淆矩阵 |
| `Agent评测/早期预警逐条结果.json` | 每条的真实标签、预测标签、risk_score、推理理由、是否命中 |

#### 2.4 接口返回格式适配

评测脚本已经兼容多种返回格式，**以下任意一种都能自动识别**：

```json
{"conclusion": "rumor", "risk_score": 0.92, "reason": "..."}
{"result": "Yes"}
{"label": "rumor"}
{"output": "Yes"}
{"prediction": "No"}
```

标签值也做了自动归一化：`"Yes"` / `"谣言"` / `"是"` 都会映射到 `rumor`。

**如果你们的接口字段名完全不同**（比如返回 `{"answer": "Yes"}`），只需要在 `Agent评测/evaluate_early_warning.py` 的 `parse_agent_response()` 函数中加一行：

```python
conclusion = (
    response_json.get("conclusion")
    or response_json.get("result")
    or response_json.get("label")
    or response_json.get("output")
    or response_json.get("prediction")
    or response_json.get("answer")        # <-- 加上你们的字段名
    or ""
)
```

---

### Step 3：跑基线评测（对照组）

#### 3.1 设置 API Key

```bash
export DASHSCOPE_API_KEY="sk-你的key"
```

#### 3.2 跑评测

```bash
cd /Users/wangsheng/Desktop/数据集/早期预警准确率/基线评测

# 先测 5 条验证
python3 baseline_direct_llm.py --limit 5

# 跑全部 200 条（预计耗时 3~5 分钟，取决于 API 速度）
python3 baseline_direct_llm.py

# 如果想换模型对比
python3 baseline_direct_llm.py --model qwen-turbo
python3 baseline_direct_llm.py --model qwen-max
```

**运行过程中你会看到**：

```
📋 测试集已加载: 200 条记录
🤖 模型: qwen-plus
📌 方法: 直接 Prompting（无 Agent 架构）
==================================================
  [  1/200] ✅ 真实=non_rumor   预测=non_rumor   (原始输出="No")  white house is aglow in the colors...
  [  2/200] ❌ 真实=unknown     预测=non_rumor   (原始输出="No")  nurses save lives of all differen...
  ...
```

**完成后自动生成**：

| 文件 | 内容 |
|------|------|
| `基线评测/基线1_裸LLM评估报告.txt` | 格式与 Agent 报告完全一致，可直接横向对比 |
| `基线评测/基线1_裸LLM逐条结果.json` | 每条的原始 LLM 输出、归一化标签、是否命中 |

> **基线的 Prompt 设计故意做得极简**：只告诉模型"判断是否谣言，输出 Yes/No/Unknown"，不给任何推理引导、不提供知识检索、不做多步验证。这就是"裸 LLM"的含义——和你们 Agent 的完整架构形成鲜明对比。

---

### Step 4：对比结果 & 写入报告

打开两份评估报告，直接对比关键数字：

```bash
# 快速查看两份报告的准确率
grep "总体准确率" Agent评测/早期预警评估报告.txt
grep "总体准确率" 基线评测/基线1_裸LLM评估报告.txt
```

#### 结题报告/答辩 PPT 中推荐的呈现方式

**表格（必放）**：

```
╔════════════════════════════════════╦══════════╦════════╦════════╦════════╗
║ 方法                               ║ Accuracy ║   P    ║   R    ║   F1   ║
╠════════════════════════════════════╬══════════╬════════╬════════╬════════╣
║ 裸 LLM 直接 Prompting (qwen-plus) ║  xx.x%   ║  0.xx  ║  0.xx  ║  0.xx  ║
║ 我们的 Agent（完整架构）            ║  xx.x%   ║  0.xx  ║  0.xx  ║  0.xx  ║
╠════════════════════════════════════╬══════════╬════════╬════════╬════════╣
║ Agent 相对提升                      ║ +xx.x pp ║       ║        ║        ║
╚════════════════════════════════════╩══════════╩════════╩════════╩════════╝
```

> pp = percentage points（百分点），比如从 72% 提升到 86% 就是 +14pp。

**话术参考**：

> "在物理切断所有传播链的极端苛刻条件下（零评论、零转发、零用户画像），我们的
> Agent 仅凭原帖纯文本即可达到 xx.x% 的早期预警准确率，比直接使用同一底座模型
> (Qwen) 的裸 Prompting 高出 xx 个百分点。这证明准确率的提升并非来自大模型本身
> 的能力，而是来自我们设计的 Agent 架构（推理链 + 知识检索 + 多步验证）。"

---

## 四、常见问题排查

### Q1: Agent 评测报 "连接失败"

```
🔴 连接失败 — 请确认 Agent 接口已启动
```

**原因**：Agent FastAPI 服务没启动，或者地址/端口不对。

**解决**：
1. 确认 Agent 服务正在运行
2. 用 `curl` 手动测一条（见 Step 2.2）
3. 如果端口不是 8000，用 `--api` 参数指定正确地址

### Q2: 基线评测报 "未设置 DASHSCOPE_API_KEY"

```
❌ 未设置 DASHSCOPE_API_KEY 环境变量
```

**解决**：执行 `export DASHSCOPE_API_KEY="sk-你的key"`。注意每开一个新终端窗口都要重新设置（或写入 `~/.zshrc`）。

### Q3: 基线评测频繁 "限流"

```
⏳ 限流，等待 4s 后重试
```

**原因**：DashScope API 有调用频率限制。

**说明**：脚本内置了自动重试和退避机制，遇到限流会自动等待后继续，不需要手动干预。如果限流严重，可以增大脚本中的 `RATE_LIMIT_DELAY` 值（默认 0.5 秒）。

### Q4: Agent 返回字段无法识别，准确率异常低

**现象**：所有预测都是空或者不匹配。

**排查**：
1. 在 `Agent评测/早期预警逐条结果.json` 中查看 `predicted_label` 是什么值
2. 如果全是空字符串或奇怪的值，说明 `parse_agent_response()` 没认出你们的返回字段
3. 参照 Step 2.4 的说明添加你们的字段名

### Q5: 想重新构建测试集

```bash
cd /Users/wangsheng/Desktop/数据集/早期预警准确率
python3 build_early_warning_testset.py
```

注意：重新构建后需要重跑两组实验，否则数据不一致。默认随机种子固定为 42，所以多次运行结果相同。如果想换一批数据，修改脚本中的 `RANDOM_SEED`。

---

## 五、测试集标签分布

| 标签 | 含义 | 数量 | 占比 |
|------|------|------|------|
| rumor | 谣言 | 78 | 39.0% |
| non_rumor | 非谣言 | 75 | 37.5% |
| unknown | 无法判断 | 47 | 23.5% |
| **合计** | | **200** | **100%** |

三类标签分布均衡，避免了类别不平衡导致准确率虚高的问题。

---

## 六、评估指标说明

两份评估报告都包含以下指标：

| 指标 | 含义 | 为什么重要 |
|------|------|-----------|
| **Accuracy** | 总体准确率 = 正确数 / 总数 | 最直观的数字，答辩首先展示 |
| **Precision** | 预测为某类的样本中有多少真的是该类 | 衡量"报错率"，高 Precision = 少误报 |
| **Recall** | 某类样本中有多少被正确识别 | 衡量"漏检率"，高 Recall = 少漏报 |
| **F1** | Precision 和 Recall 的调和平均 | 综合指标，适合写进论文 |
| **混淆矩阵** | 每个真实类别被预测成了什么 | 发现系统的弱点在哪（比如 unknown 容易被误判为 non_rumor） |

---

## 七、完整命令速查

```bash
# ===== 环境准备 =====
pip install requests openai
export DASHSCOPE_API_KEY="sk-你的key"

# ===== Step 1: 构建测试集 (已完成可跳过) =====
cd /Users/wangsheng/Desktop/数据集/早期预警准确率
python3 build_early_warning_testset.py

# ===== Step 2: 跑 Agent 评测 =====
cd /Users/wangsheng/Desktop/数据集/早期预警准确率/Agent评测
python3 evaluate_early_warning.py --limit 5        # 先测 5 条
python3 evaluate_early_warning.py                   # 全部 200 条

# ===== Step 3: 跑基线评测 =====
cd /Users/wangsheng/Desktop/数据集/早期预警准确率/基线评测
python3 baseline_direct_llm.py --limit 5            # 先测 5 条
python3 baseline_direct_llm.py                      # 全部 200 条

# ===== Step 4: 对比结果 =====
grep "总体准确率" ../Agent评测/早期预警评估报告.txt
grep "总体准确率" 基线1_裸LLM评估报告.txt
```
