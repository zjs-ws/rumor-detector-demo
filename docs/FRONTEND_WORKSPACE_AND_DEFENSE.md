# RumorBuster 前端工作台与答辩卡

## 产品定位

前端不是“让大模型自由判断真假的聊天壳”，而是 LangGraph 核验状态的可视化工作台。普通用户首先看到主张、确定性规则结论和采用证据；RAG、LoRA、文本风险及底层 trace 被明确放在辅助层或技术审计层。

数据链如下：

```text
浏览器
→ Nginx
→ Next.js
→ useThreadStream
→ LangGraph 流式状态
→ rumor_workflow（执行过程）
→ rumor_report（稳定结果）
→ RumorReportViewModel（客户端安全标准化）
→ 结构化报告、打印、Markdown 与 JSON
```

## 组件调用链

```text
新建核验页
├── Welcome：产品定位、示例和能力边界
├── InputBox：统一文字/URL 输入，隐藏通用模型选择器
└── ChatBox
    ├── RumorWorkflowStatus：七阶段与四个并行分支
    └── RumorReportCard
        ├── buildRumorReportViewModel
        ├── 结论首屏
        ├── 证据筛选与子主张对照
        ├── 分析和传播信息
        └── 折叠的技术审计
```

历史实测页读取仓库中脱敏保存的真实 V3 运行结果，并复用 `RumorReportCard`。页面会显示“历史实测结果”和实际运行日期，不播放实时动画，也不把存档冒充新运行。

## 框架与团队归属

- DeerFlow 前端基础：工作区布局、消息流、通用 Agent 页面、模型选择与基础 UI 组件。
- LangGraph：线程、流式事件、checkpoint 中的 `rumor_workflow` 和 `rumor_report`。
- 团队前端改造：证据实验室视觉、七阶段状态、并行分支卡、报告 ViewModel、证据筛选、子主张对照、历史实测页、安全导出和划词入口。

Agent、MCP 与 Skill 路由没有删除，以保留 DeerFlow 扩展能力；它们仅从 RumorBuster 主导航移至“设置与关于 → 框架扩展能力”，不作为项目核心算法宣传。

## 十问十答

### 1. 为什么不直接解析 Markdown？

Markdown 是大模型组织出的非稳定文本，字段可能遗漏、改名或产生无法校验的链接。结构化 `rumor_report` 能逐项绑定规则 verdict、证据 ID 和来源信息；ViewModel 再负责版本兼容与安全降级。

### 2. `rumor_workflow` 和 `rumor_report` 有什么区别？

`rumor_workflow` 是运行态，记录当前 stage、分支状态、降级码和 trace；`rumor_report` 是汇合、裁决和终局校验后的稳定结果。前者回答“执行到哪”，后者回答“依据什么得到什么结论”。

### 3. 为什么前端不能修改 verdict？

verdict 来自后端确定性证据规则。前端只做枚举翻译、布局和异常字段降级；如果前端自行改判，网页、API、导出和 checkpoint 会互相矛盾。

### 4. 为什么 LoRA 和证据必须分层展示？

LoRA 只读取文本并输出风险标签，没有读取本轮网页证据。证据卡呈现可追溯事实来源；将两者混在一起会错误放大分类器权威。

### 5. 为什么并行分支不能画成顺序步骤？

RAG、普通网页研究、LoRA 和专业权威研究在 StateGraph 中并行启动，fan-in 后才统一校验。画成串行会错误描述系统性能和控制流。

### 6. report-v1/v2/v3 怎样兼容？

所有版本先进入 `buildRumorReportViewModel`。缺失字段变成明确空状态，未知枚举显示“未知状态”，非法分类值绝不会默认为“非谣言”，少于三个节点的时间线不展示。

### 7. 搜索失败后页面怎样降级？

对应分支显示黄色“不可用”和降级原因，其他成功分支继续汇合，系统仍进入规则裁决。证据达不到门槛时输出“证据不足”，而不是把技术失败伪装成明确真假。

### 8. 浏览器插件为什么使用 fragment？

选中文字和来源 URL 放在 `#fragment` 中。fragment 不会随 HTTP 请求进入 Nginx 访问日志；前端读取后清除地址栏，用户确认后才提交核验。

### 9. 为什么正式导出不包含 reasoning？

reasoning 不是经证据规则校验的公开报告内容，可能包含内部过程、工具参数或敏感配置。正式导出只保留结构化报告、必要运行元数据和公开对话。

### 10. 删除这层前端改造会失去什么？

后端仍可运行，但用户无法快速区分规则结论、证据、模型信号和运行降级，也无法安全查看旧报告、历史实测案例或得到一致的公开导出。这层改造解决的是可理解性、可追溯性和演示稳定性。

## 两分钟讲解提纲

RumorBuster 的前端从 DeerFlow 通用聊天工作区改造成证据实验室。输入仍复用同一个流式线程接口，但默认核验页隐藏通用模型选择器，因为切换主模型不能改变证据规则。运行时先展示七个真实阶段，在并行取证阶段横向展示 RAG、普通网页、专业权威和 LoRA 四个分支，单一分支不可用不会把整个流程画成失败。

报告生成后，前端不解析大模型 Markdown，而是读取 checkpoint 中的 `rumor_report`，通过 ViewModel 统一处理 v1、v2、v3、未知枚举、非法 URL 和缺失字段。首屏只放规范化主张、规则 verdict、证据强度和数量；随后才是采用证据和子主张；RAG、LoRA 和文本风险始终标明辅助属性；trace 默认折叠。Markdown、JSON 和打印与网页使用同一个结构化来源，公开导出删除 reasoning、工具参数和敏感字段。因此我们的前端工作不仅是换皮，而是把事实核验的可信边界准确呈现给用户。

## 本地验收

```bash
corepack pnpm --dir frontend test
node --test browser-extension/tests/*.mjs
corepack pnpm --dir frontend format
corepack pnpm --dir frontend lint
corepack pnpm --dir frontend typecheck
corepack pnpm --dir frontend build

docker compose -f compose.prod.yaml config -q
docker compose -f compose.prod.yaml up -d --build
python3 scripts/check_production_ready.py
```

浏览器至少检查 `390×844`、`768×1024`、`1280×720` 和 `1440×900` 的亮暗主题，并覆盖无证据、全部排除、分类器不可用、分支混合状态、时间线不足和未知枚举。
