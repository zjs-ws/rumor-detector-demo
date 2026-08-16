# RumorBuster 本地向量 RAG 实现说明

## 1. 课程链路与项目链路

本实现对应课程资料中的标准流程：

```text
复核文档
→ LangChain Document Loader
→ RecursiveCharacterTextSplitter
→ HuggingFace 中文 Embedding
→ Chroma 持久化向量库
→ similarity retriever
→ 检索片段注入解释 Prompt
```

RumorBuster 在此基础上增加关键词召回、子主张查询、RRF 融合、来源元数据、时效提醒和安全降级：

```text
最多 3 个实质子主张
├── Chroma 语义检索 Top-8
└── 字符 2—4 gram TF-IDF Top-8
        ↓
      RRF 融合
        ↓
每个子主张最多 2 条，整轮最多 6 条
        ↓
受长度限制的历史知识上下文
        ↓
解释模型（不得改变规则 verdict）
```

## 2. 语料与索引

- 正式种子语料：`verified_rumors.jsonl` 中 30 条 `review_status=reviewed` 的核查记录；
- 扩展语料：`data/rag_documents/` 下 Markdown、TXT、HTML 或 PDF；
- 每份扩展文档必须有同名 `.meta.json`，并提供公开 HTTP(S) 来源、发布主体、复核日期和 `review_status=reviewed`；
- 未复核网页抓取结果只进入 `runtime/rumorbuster/rag/staging/`，不能自动进入正式索引；
- 精确重复正文按 SHA-256 去重；未来日期、非法日期和不可追溯文档拒绝建库。

默认参数：

```text
Embedding: GanymedeNil/text2vec-large-chinese
device: cpu
chunk_size: 500
chunk_overlap: 80
vector store: Chroma / cosine
dense threshold: 0.35
sparse threshold: 0.05
RRF k: 60
```

索引不提交 Git，存放在 `runtime/rumorbuster/rag/`。每次构建根据语料、模型和切片参数生成版本号；`current.json` 指向当前版本，`manifest.json` 记录文档数、切片数、语料哈希和阈值。

## 3. 与 V3 工作流的关系

RAG 是 V3 并行取证阶段的一个独立分支，与普通网页研究、传播脉络研究、专业权威研究和 LoRA 文本分类同时启动。同步 Embedding 工作通过工作线程执行，并受 20 秒预算控制，避免阻塞 LangGraph 的异步事件循环。传播脉络研究与 RAG 相互独立：RAG 召回本地已复核历史知识，传播分支联网抓取有日期的公开页面。

RAG 返回：

- 命中的 `document_id`、`chunk_id` 和关联 `claim_id`；
- 稠密、稀疏和融合分数；
- 历史结论、片段、发布主体、来源 URL、发布日期和复核日期；
- 检索模式、索引版本、文档/切片数量和降级码。

解释节点最多接收 6 个片段、3600 个字符。提示词明确要求：历史知识只能说明相似背景，人物、时间、地点或数量不一致时必须指出，不能复制历史 verdict。

## 4. 为什么 RAG 不参与证据门槛

向量相似只表示文本语义接近，不表示当前主张为真或为假。历史记录还可能存在时效、主体、地点和条件差异。因此：

- RAG 不能成为 A/B 级当前事实证据；
- RAG 不能覆盖规则裁决；
- RAG 中的来源 URL 只能作为后续抓取候选，重新抓取并通过本轮来源、时间、独立性校验后，才可能成为证据；
- 前端不把相似度显示成“可信度”。

它的关键价值是找出旧谣言变体、补充检索词、提示应核查的历史背景，并让解释模型获得可追溯的相关片段。

## 5. 构建、评测与降级

```bash
# 只校验语料和切片
docker compose -f compose.prod.yaml run --rm -T langgraph \
  uv run python scripts/build_rag_index.py --validate-only

# 下载 Embedding 并构建持久 Chroma 索引
docker compose -f compose.prod.yaml --profile maintenance run --rm rag-indexer

# 评测旧关键词基线与混合检索
docker compose -f compose.prod.yaml run --rm -T langgraph \
  uv run python scripts/evaluate_rag_retrieval.py --mode sparse
docker compose -f compose.prod.yaml run --rm -T langgraph \
  uv run python scripts/evaluate_rag_retrieval.py --mode hybrid
```

索引不存在、版本不匹配、损坏、模型加载失败或超时时，系统返回明确降级码并自动使用 TF-IDF；RAG 整体失败也不会取消其他取证分支。

当前 30 条 `evaluation/rag_cases.jsonl` 是种子记录的改写检索测试。Recall@1/3 可用于防止代码回归，但不能证明对开放互联网主张的泛化性能。扩展语料后应增加独立改写、无关负例、跨领域和时效冲突案例。

## 6. 框架与团队归属

- LangChain：Document、Loader、RecursiveCharacterTextSplitter 和 HuggingFace Embedding 封装；
- Chroma：本地向量持久化与相似度检索；
- RumorBuster：复核语料规范、中文切片参数、版本化索引、子主张检索、TF-IDF、RRF、降级策略、Prompt 边界、前端审计和评测脚本。

答辩时可以说“使用 LangChain 与 Chroma 实现本地向量 RAG，并做了谣言核验领域化改造”，不能说向量数据库或 Embedding 算法是团队从零实现。
