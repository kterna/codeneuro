# 架构

CodeNeuro 是模块化单体：同一 Hub 提供 Web、HTTP API 与 stdio/Streamable HTTP MCP，以本地 SQLite 保存业务知识和实际下发。

## 分层

- `modules/`：领域数据与纯策略，不依赖数据库或网络框架。
- `workflows/`：需求/任务生命周期、上下文装配、规则治理、主题和反馈等用例。
- `ports.py`：工作流依赖的仓储和事务边界。
- `adapters/sqlite/`：当前表结构与 SQLAlchemy Core 仓储。
- `adapters/http/`、`adapters/mcp/`：参数校验和 DTO 映射，共享工作流。
- `web/`：Vue 3、TypeScript、Vite 工作台；构建产物位于 `src/codeneuro/static/`。

依赖从接口流向工作流与领域，架构测试检查导入方向。没有宿主品牌分支、隐式全局服务或自动执行宿主测试的组件。

## 业务关系

Project → Requirement → Task。Requirement 保存整体目标、验收要求和验收结论；Task 保存独立实现范围、验证要求及结果。Task 验证完成只推动父需求进入待整体验收，用户确认后才完成父需求。

归档和软删除使用独立时间字段。记录修订号防止并发覆盖；需求、任务与规则快照保留当时内容。子任务变化同步更新父需求修订，验收检查在同一写事务里完成。

当前运行时没有 Session 实体。工作范围由明确的 Project/Task/记录 ID 决定。Worktree/source 是可选的客户端声明，既不证明身份，也不推导业务任务。

## 上下文与证据

上下文采用短只读快照、事务外纯装配、短写事务重核修订的流程，避免长时间持锁和混合新旧数据。重核范围包括项目规则、主题目录、父需求、Task 和任务知识；冲突时有限重算。

调用方显式选择优先级、主题或真实文件。主题决定业务适用性；无主题时按文件匹配。Task 查询附带父目标与自身范围，不包含兄弟任务。被选中且适用的 P0 全文保留；预算省略明确返回。

Delivery 保存实际正文与引用；预览不生成真实下发凭据。请求回执按项目、操作和 request_id 保存输入指纹与原结果。反馈引用真实 Delivery；0 分仅用于统计，不压缩其他 Agent 的正文。

规则验证按声明的检查和测试项绑定宿主报告。同事件的时间区或排序差异不会增加证据次数。规范规则走人工审阅；长期契约修改使用固定候选和目标修订。所有证据仍是客户端上报，不等于 Hub 执行或认证。

## 存储与运行

只维护 `adapters/sqlite/schema.py` 中的当前模型，没有数据库升级链或协议版本分支。`codeneuro init-db --db ...` 在空库建表；服务启动只检查实际表结构，不隐式改库。既有本地数据由 `scripts/migrate_local_data.py` 一次性转到新库，源库保留。

SQLite 写事务使用 `BEGIN IMMEDIATE`，连接启用外键和有界等待。读写事务短且显式，历史快照与业务更新同事务提交。详情和列表有界，账本使用真实聚合计数。

Web、同机 MCP 和 HTTP MCP 共用 Hub 本机数据库。远程客户端连接 HTTP，不在共享网络盘直接并发打开 SQLite。文件查询只校验声明路径的语法和项目业务范围，不声称扫描了远端工作区。

Web 与 MCP 均无鉴权。actor/human 等字段仅是操作来源标签。默认监听回环地址；工程部署和 Git 提交要求见项目已有约定。

业务细节见[需求与任务](requirement-task-hierarchy.md)、[主题](topics.md)、[规则治理](governance.md)和[接口](mcp-resources.md)。
