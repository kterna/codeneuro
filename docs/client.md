# Hub 客户端与身份边界

当前产品提供同机 stdio MCP、受认证的远程 streamable HTTP MCP、Web HTTP API；三者的业务工具定义和应用用例同源。客户端获得的 `Actor` 项目范围来自操作员在环境中配置的 Token，不能靠模型传入 `actor_id`、项目 ID 或 `reviewed=true` 自我授权。人类审阅既有长期契约只能由 human 身份完成。

远程 MCP 客户端调用 `codeneuro_start_session` 时可以附带 `workspace`、机器名、平台、仓库身份与分支。Hub 根据身份及路径生成稳定 Worktree ID，**只证明“这个认证客户端做过该声明”**，不假称读取或验证过远端工作区。上下文路径仍须为工作区相对 POSIX 路径；不支持把 NAS 上的目录当作办公机目录。

所有 Rule、Requirement、版本和实际 Delivery 保存在 Hub 数据库；没有本地静态规则文件或同步守护进程。`codeneuro_get_context` 需要 Agent 主动调用，预览不计作真实下发。评分只能引用该会话真实取得的 Rule 版本和 `delivery_id`；0 代表会话已知，效用均分排除 0，P0 仍完整下发。

Web 使用 `/app/`；MCP 连接与配置见 [标准接入](agent-integrations.md)。当前不内置 CodeNeuro 远程路径自动发现器或宿主钩子；不要引用旧版 `codeneuro.client`、`codeneuro.cli`、`sync/export` API。
