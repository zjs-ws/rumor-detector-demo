# 指标五：极低误报率 / 假阳性率极小化 (False Positive Minimization)

## 一、背景与降维打击点

在辟谣业务中，**"把真新闻错判成谣言（误报）"的代价远大于"漏掉一个谣言"**。

- 一旦系统把某条真实新闻标为谣言，可能导致信息恐慌、用户信任崩塌。
- 传统分类算法（SVM、CNN、TF-IDF）遇到文本里带有"爆炸""死亡""紧急"等敏感词，就容易直接拉响警报，造成大量误报。
- 而 Agent 具备 **「外部工具查证」** 能力：只有在通过搜索引擎/知识库查到明确的反面证据时才判定为谣言。面对"五星级厕所耗资200万"这种看似荒谬但确有其事的新闻，Agent 能正确放行，传统模型则大概率误报。

**核心指标**：
- **误报率 (False Positive Rate, FPR)** = 真实非谣言被错判为谣言的比例
- 目标：Agent 在保持高检出率的同时，将 FPR 压到极低水平

## 二、环境准备

```bash
pip install requests openai
```

- `requests`：调用 Agent FastAPI 接口
- `openai`：调用基线 Qwen LLM（通过 DashScope 兼容接口）

基线 LLM 需要设置 API Key：

```bash
export DASHSCOPE_API_KEY="sk-xxxxxxxx"
```

## 三、完整操作步骤

### 第一步：构造误报压力测试集

```bash
cd 极低误报率（5）
python3 build_fpr_stress_testset.py
```

**做了什么**：
- 从原始数据中筛选所有 **non_rumor（真实新闻）** 样本
- 优先挑选包含「爆炸、死亡、疫情、紧急、震惊」等敏感词的真新闻（约 60%）
- 补充 15 条精心设计的合成样本（如"某市出现猴痘确诊""高速货车侧翻"），这些文本看起来极像谣言但确实是真新闻
- 总计约 150 条，**全部标签为 non_rumor**

**输出**：
- `误报压力测试集.json` —— 压力测试数据
- `误报压力测试集_统计.txt` —— 样本构成统计

可选参数：

```bash
python3 build_fpr_stress_testset.py --sample 200   # 抽 200 条
```

### 第二步：评测 Agent 的误报率

确保你的 Agent FastAPI 服务已启动，然后：

```bash
python3 evaluate_false_positive.py --target agent --api http://127.0.0.1:8000/detect
```

先测 10 条验证连通性：

```bash
python3 evaluate_false_positive.py --target agent --limit 10
```

**输出**：
- `Agent_误报评测报告.txt` —— 包含 FPR、各敏感类别误报率、误报案例列表
- `Agent_误报评测结果.json` —— 逐条详细结果

### 第三步：评测基线 LLM 的误报率

```bash
export DASHSCOPE_API_KEY="sk-xxxxxxxx"
python3 evaluate_false_positive.py --target baseline
```

换模型：

```bash
python3 evaluate_false_positive.py --target baseline --model qwen-turbo
```

**输出**：
- `基线_误报评测报告.txt`
- `基线_误报评测结果.json`

### 第四步：生成对比报告

```bash
python3 compare_fpr.py
```

**做了什么**：
- 横向对比 Agent vs 基线在压力测试集上的 FPR
- 按敏感词类别分解（哪类词最容易诱发基线误报）
- 如果存在指标一的全量数据结果，还会提取常规数据上的 non_rumor 误报率作为二次验证
- 生成答辩话术参考和可视化建议

**输出**：
- `极低误报率_对比报告.txt` —— 综合对比
- `极低误报率_详细数据.json` —— 结构化数据

## 四、如何对接你的 Agent

`evaluate_false_positive.py` 通过 HTTP POST 调用 Agent 接口：

```
POST http://127.0.0.1:8000/detect
Content-Type: application/json

{"text": "【突发】某地发生4.2级地震，暂无人员伤亡报告。"}
```

Agent 应返回 JSON，支持以下格式之一：

```json
{"conclusion": "non_rumor", "risk_score": 0.15, "reason": "经查证..."}
```

```json
{"result": "No"}
```

```json
{"label": "non_rumor"}
```

如果你的接口地址或字段不同，修改以下位置：
- `DEFAULT_API_URL` —— 接口地址
- `parse_agent_response()` —— 返回值解析逻辑

## 五、报告解读

### 核心指标

| 指标 | 含义 | 理想值 |
|------|------|--------|
| FPR (误报率) | 真新闻被错判为谣言的比例 | 越低越好，最佳为 0% |
| 准确率 | 正确识别为非谣言的比例 | 越高越好 |
| 各类别 FPR | 按敏感词类别分解的误报率 | 定位薄弱点 |

### 各敏感类别解读

报告会列出 13 类敏感词的误报率分解，例如：

```
  类别        Agent FPR   基线 FPR   Agent优势
  自然灾害      0.0%       18.5%     +18.5%
  疫情类        0.0%       22.0%     +22.0%
  情绪煽动      5.0%       35.0%     +30.0%
```

这说明基线在遇到疫情/灾害类真新闻时误报严重，而 Agent 通过外部查证规避了这类误报。

## 六、常见问题

**Q: 如果 Agent 也有误报怎么办？**
分析 `Agent_误报评测结果.json` 中 `is_false_positive: true` 的案例，看看误报集中在哪类敏感词上，可以据此优化 Agent 的查证策略。

**Q: 合成样本会不会让数据不真实？**
合成样本仅占 10%，且都是参照真实新闻格式编写的。大部分样本来自原始数据集的真实 non_rumor 数据。

**Q: 可以和指标一的数据联动吗？**
可以。`compare_fpr.py` 会自动从指标一的 `早期预警逐条结果.json` 和 `基线1_裸LLM逐条结果.json` 中提取 non_rumor 子集的误报率，形成"常规数据 + 高压数据"的双重对比。

## 七、答辩展示建议

1. **一张对比柱状图**：Agent FPR vs 基线 FPR，数字越低越好
2. **敏感类别热力图**：展示基线在各类敏感词上的高误报率，而 Agent 全面压低
3. **2~3 个典型案例**：选出含有"爆炸""死亡"等词的真新闻，展示 Agent 正确识别为非谣言，而基线误判为谣言
4. **一句总结**："Agent 因为有外部工具查证环节，不会被敏感词欺骗，误报率仅 X%，是基线的 1/N"
