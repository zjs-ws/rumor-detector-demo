# 评论质证扩展接口（未启用）

RumorBuster 当前不抓取评论，不构造传播树，也不把评论计入 A/B 证据门槛。下面的结构仅用于后续兼容设计。

输入：

```json
{
  "social_context_input": {
    "source": "user_supplied",
    "comments": [
      {
        "id": "comment-1",
        "text": "评论正文",
        "parent_id": null,
        "published_at": "2026-08-13T10:00:00+08:00",
        "url": "https://example.com/comments/1"
      }
    ]
  }
}
```

未来输出：

```json
{
  "social_context_analysis": {
    "stance_summary": {},
    "challenges": [],
    "external_references": [],
    "possible_mutations": []
  }
}
```

约束：评论只能作为检索和传播线索；其中的 URL 必须重新抓取；人数、点赞和情绪不能决定真假。本阶段报告应明确显示“评论质证未启用”。
