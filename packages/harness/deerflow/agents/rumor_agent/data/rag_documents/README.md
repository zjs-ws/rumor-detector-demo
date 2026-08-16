# RumorBuster RAG 文档目录

这里存放经过人工复核、允许进入本地向量知识库的 Markdown、TXT、HTML 或 PDF 文件。

每个正文文件必须有同名侧车元数据，例如：

```text
example.md
example.md.meta.json
```

侧车至少包含：

```json
{
  "document_id": "authority-example-001",
  "canonical_claim": "待核查主张",
  "historical_verdict": "rumor",
  "publisher": "发布主体",
  "source_url": "https://example.org/source",
  "published_at": "2026-08-14",
  "reviewed_at": "2026-08-14",
  "review_status": "reviewed",
  "category": "public_policy"
}
```

没有侧车或 `review_status` 不是 `reviewed` 的文件不会进入正式索引。课程资料、论文、模型权重和网页抓取 staging 不放在这里。
