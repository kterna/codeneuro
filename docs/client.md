# 客户端使用

CodeNeuro 是主动查询的知识 Hub，支持 stdio MCP 和 Streamable HTTP MCP，配置示例见 [README](../README.md)。同机 stdio 使用 Hub 本机数据库；远程客户端连接 `http://<hub>:8801/mcp/`，不直接打开共享盘 SQLite。

Agent 在分析业务或操作相关文件前查询适用上下文，宿主执行编码和测试。安装 MCP 不会自动拦截工具或注入每次读取。Web、HTTP 与 MCP 均无鉴权，默认监听本机；actor、human、Worktree/source 都只是来源声明。

1. 列出已登记项目，确认当前项目。
2. 如涉及业务任务，先列出需求与子任务，明确选择已有 Task；需要创建时按用户授权创建父需求或子任务。
3. 直接调用 get_context，传 project_id、可选 task_id、明确 priorities，以及 topics 或真实相对文件。
4. 在选定 Task 上推进实现、记录实际测试、提交独立验证。全部子任务完成后，父需求等待用户整体验收。

没有 Session 的创建、复用、关闭或 debug 开关。单纯项目规则查询可不选 Task；工作区路径和调用历史不自动选择 Task。可选 source 仅记录来源。

任务开发完成先转 testing；验证后转 completed 并填写 verification_summary。父需求整体完成须用户确认，提交 completion_summary 与确认原因。归档只收纳记录；已完成工作要继续修改时显式重开。记录更新/删除使用当前 expected_version 和 reason，冲突时先读最新记录再作决定。

主题使用项目受控词表，先 list_topics/get_topic 查定义，不能凭空发明标签。主题查询需要项目分类确认；尚未启用时可以按真实文件查询。等级是精确集合，P0 不被隐式加入；匹配且已选中的 P0 保持全文。

相同 request_id 重放原快照，新请求读取最新知识。需要查看当时内容时按 delivery_id 读取，不用新查询冒充原下发。反馈只能引用真实下发；0 分只作已知统计，不简写后续内容。预览不生成实际 Delivery。

列表和修订历史分页，摘要截断会明确标记，需要完整文本时使用 get。接口参数见 [MCP 与 HTTP](mcp-resources.md)，治理约束见[规则治理](governance.md)。
