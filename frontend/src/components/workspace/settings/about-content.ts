/** Product information shown in the workspace settings. */
export const aboutMarkdown = `# 关于 RumorBuster

RumorBuster 是一个面向网络传言、新闻说法和可疑信息的谣言检测与事实核验项目。

## 当前版本可以做什么

- 分析用户提交的文字内容
- 识别来源缺失、逻辑漏洞和可疑表述
- 区分已知事实、合理推断与证据不足
- 给出进一步核验所需的证据清单

## 当前限制

联网搜索、专业领域 RAG、微调分类模型、完整登录系统和生产部署仍在开发中。

在没有可靠外部证据时，RumorBuster 会明确说明证据不足，而不会把推测写成事实。

## 项目源码

[github.com/zjs-ws/rumor-detector-demo](https://github.com/zjs-ws/rumor-detector-demo)

## 开源致谢

本项目基于包括 DeerFlow、LangGraph 在内的开源组件进行开发。相关许可证和署名保留在源码仓库中。
`;
