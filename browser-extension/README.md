# RumorBuster 划词核验扩展

这是无需发布到商店即可本地加载的 Chrome Manifest V3 扩展。

## 本地安装

1. 先确认 RumorBuster 已在 `http://localhost:8080` 运行。
2. 在 Chrome 打开 `chrome://extensions`。
3. 开启右上角“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择本仓库的 `browser-extension/` 目录。

## 使用

在任意 HTTP 或 HTTPS 网页中选中文字，点击右键并选择“用 RumorBuster
核验”。扩展会打开一个新的 RumorBuster 对话，并预填选中文字和来源页面。
内容不会自动发送，用户可以在发送前检查或修改。

如需切换到其他本地端口或后续云端地址，可在扩展详情页点击“扩展程序选项”修改 RumorBuster 地址。扩展只接受 HTTP(S) 地址。

选中文字通过 URL fragment 传递，不会出现在 RumorBuster 服务的 HTTP 请求
或访问日志中。前端读取内容后会立即清除地址栏里的 fragment。
