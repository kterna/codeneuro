# 通用 MCP 接入

CodeNeuro 不发布 Codex、Claude、Hermes、Pi 等宿主专用 hook/extension，也不拦截宿主自带读写工具。宿主若支持标准 MCP，直接使用同一套 CodeNeuro 工具契约。

- **同机 stdio**：在受信任机器上运行 `python -m codeneuro mcp --db /absolute/path/state.db`，无需客户端凭据。
- **远程 Hub**：将支持 streamable HTTP MCP 的客户端接入可信网络中的 `http(s)://your-trusted-hub/mcp/`，无需 Token。**能访问 Hub 监听地址的人可以读写数据；默认仅绑定本机回环地址，不要把无鉴权的服务直接暴露公网。**不要通过网络文件系统共享 SQLite 文件；远端工作区路径是客户端声明，Hub 不读取远端源码。宿主如不支持 MCP，需要宿主侧独立的标准协议适配器，不在 CodeNeuro 核心写品牌分支。

Agent 先调用 `codeneuro_task(project_id, action="list")`，本地正则匹配标题及描述，明确选定任务或使用 create 新建。需要继续归档任务时，以当前 version 调用 update，将 changes.status 设为 active。Task/Requirement 的增删改查分别由 `codeneuro_task`、`codeneuro_requirement` 统一承担，参数见 [CRUD 契约](mcp-resources.md)；不再为归档、恢复等状态操作增加独立工具或专用参数。随后通过 `codeneuro_start_session` 绑定 active/testing Task；需要评分或提交 Issue 时显式传入 debug=True。文件或纯业务操作前**主动**调用 `codeneuro_get_context`，显式传入非空 priorities 及 topics/真实文件（至少一种），取得结构化下发凭据。既有长期契约的修改仍须人类审阅。

需求操作直接以 task_id 定位，无需为了管理需求而创建 Session。新需求使用 create；修订正文、归档和重开均使用 update；删除使用 delete。归档需 changes.status=archived 和非空 changes.summary，重开需 changes.status=active。更新/删除携带 id、expected_version 和 reason。需求初始原文、旧版本、历史下发均保留；软删除不等于完成，重开不恢复停用规则。

MCP 上报测试工具仅**记录宿主报告**及其时间、可选路径、退出码和明确测试项结果；`observe_rule` 将检查 ID 绑定规则版本及计划中的条款/测试 ID。CodeNeuro 不执行命令；不能把 `client_reported` 凭据说成 Hub 验证。安装 MCP 本身不会自动向模型每次读取注入规则。操作边界和命令见 [README](../README.md)。Topic CRUD、破坏性接口改动、验证计划和逐项目切换见 [v2 契约](topics-v2.md)。
