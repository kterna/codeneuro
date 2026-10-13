# Hub 客户端与工作区声明

当前产品提供同机 stdio MCP、远程 streamable HTTP MCP 和 Web HTTP API；不需要登录或 Token。直接打开 `/app/` 即加载项目。Web 的人工审阅入口与 MCP 工具分开，但**没有鉴权，不能据此证明真实操作者身份**。默认只监听本机；绑定非本机地址前须自行确认网络可信，不得直接暴露公网。

远程 MCP 客户端调用 `codeneuro_start_session` 时可以附带 `workspace`、机器名、平台、仓库身份与分支。Hub 根据客户端声明及路径生成稳定 Worktree ID，**只证明服务收到了该声明**，不假称读取或验证过远端工作区。上下文路径仍须为工作区相对 POSIX 路径；不支持把 NAS 上的目录当作办公机目录。

所有 Rule、Requirement、版本和实际 Delivery 保存在 Hub 数据库；没有本地静态规则文件或同步守护进程。`codeneuro_get_context` 需要 Agent 主动调用，预览不计作真实下发。评分只能引用该会话真实取得的 Rule 版本和 `delivery_id`；0 代表会话已知，效用均分排除 0，P0 仍完整下发。特别注意：评分（`rate_rule`）与问题报告（`report_issue`）仅在会话以 `debug=True` 启动时允许调用；常规会话默认 `debug=False`，防止生产环境误记诊断数据。

Web 使用 `/app/`；MCP 连接与配置见 [标准接入](agent-integrations.md)。当前不内置 CodeNeuro 远程路径自动发现器或宿主钩子；不要引用旧版 `codeneuro.client`、`codeneuro.cli`、`sync/export` API。
