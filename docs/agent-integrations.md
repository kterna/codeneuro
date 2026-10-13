# 通用 MCP 接入

CodeNeuro 不发布 Codex、Claude、Hermes、Pi 等宿主专用 hook/extension，也不拦截宿主自带读写工具。宿主若支持标准 MCP，直接使用同一套 CodeNeuro 工具契约。

- **同机 stdio**：在受信任机器上运行 `python -m codeneuro mcp --db /absolute/path/state.db`，无需客户端凭据。
- **远程 Hub**：将支持 streamable HTTP MCP 的客户端接入可信网络中的 `http(s)://your-trusted-hub/mcp/`，无需 Token。**能访问 Hub 监听地址的人可以读写数据；默认仅绑定本机回环地址，不要把无鉴权的服务直接暴露公网。**不要通过网络文件系统共享 SQLite 文件；远端工作区路径是客户端声明，Hub 不读取远端源码。宿主如不支持 MCP，需要宿主侧独立的标准协议适配器，不在 CodeNeuro 核心写品牌分支。

Agent 先调用 `codeneuro_list_tasks`，本地正则匹配标题及描述，明确选定/创建 Task，再注册会话（若后续需要评分或提交 Issue，必须显式传入 `debug=True`；默认 `debug=False` 会拒绝这两项操作以防生产会话产生诊断污染）并提交 Requirement。文件工作前**主动**调用 `codeneuro_get_context`，取得结构化下发凭据；在 Debug 会话中可提交实际观察的 Finding/Issue 和按版本评分。已完成需求带摘要即时归档。已存在长期契约的修改必须经人类审阅。

MCP 上报测试工具仅**记录宿主报告**及其时间/路径/退出码，CodeNeuro 不执行命令；不能把 `client_reported` 凭据说成 Hub 验证。安装 MCP 本身不会自动向模型每次读取注入规则。操作边界和命令见 [README](../README.md)。
