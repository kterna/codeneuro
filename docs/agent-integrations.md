# 通用 MCP 接入

CodeNeuro 不发布 Codex、Claude、Hermes、Pi 等宿主专用 hook/extension，也不拦截宿主自带读写工具。宿主若支持标准 MCP，直接使用同一套 CodeNeuro 工具契约。

- **同机 stdio**：在受信任机器上运行 `python -m codeneuro mcp --db /absolute/path/state.db`，并由宿主运行环境提供 `CODENEURO_CLIENTS`、其所引用的 Token 环境变量及 `CODENEURO_TOKEN`。Token/项目范围由操作员配置，不写入仓库。
- **远程 Hub**：将支持 streamable HTTP MCP 的客户端接入 `https://your-trusted-hub/mcp/`，使用 `Authorization: Bearer <项目客户端令牌>`。不要通过网络文件系统共享 SQLite 文件；远端工作区路径是客户端声明，Hub 不读取远端源码。宿主如不支持 MCP，需要宿主侧独立的标准协议适配器，不在 CodeNeuro 核心写品牌分支。

Agent 先调用 `codeneuro_list_tasks`，本地正则匹配标题及描述，明确选定/创建 Task，再注册会话并提交 Requirement。文件工作前**主动**调用 `codeneuro_get_context`，取得结构化下发凭据；提交实际观察的 Finding/Issue 和按版本评分。已完成需求带摘要即时归档。已存在长期契约的修改必须经人类审阅。

MCP 上报测试工具仅**记录宿主报告**及其时间/路径/退出码，CodeNeuro 不执行命令；不能把 `client_reported` 凭据说成 Hub 验证。安装 MCP 本身不会自动向模型每次读取注入规则。操作边界和命令见 [README](../README.md)。
