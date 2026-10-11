# CodeNeuro 模块化单体重建规范

产品行为以 [现行产品契约](product-contract.md) 和白皮书中经后续决策确认的流程为准；旧 R09 宿主钩子、R10–R11 静态副本/同步不是目标。新核心已归位 `src/codeneuro/`，旧核心、旧版宿主钩子、静态导出/同步与对应测试已从工作树移除。历史文档只作来源核对，不再定义运行时入口。

## 依赖与边界

采用 Python 3.11、FastAPI/Pydantic、官方 MCP SDK、SQLAlchemy 2 Core、Alembic；工作台采用 Vue 3、TypeScript、Vite。领域模块和工作流不可导入 SQLAlchemy、MCP SDK、FastAPI 或旧 `codeneuro`；接口只做身份与 DTO 映射；SQL 在 SQLite 适配器内。`bootstrap` 显式装配，拒绝隐式全局单例、通用插件框架和宿主品牌分支。用架构测试保护 import 方向。

```text
modules/{workspaces,tasks,knowledge,context,findings}   纯数据与策略
workflows/{workspaces,requirements,knowledge,context,feedback,ledger}  用例与事务编排
ports.py                                              真实用例需要的仓储/UoW 契约
adapters/sqlite/{schema,uow,workspaces,requirements,knowledge,context,feedback,audit}
                                                       SQL、短事务、不可变版本引用
adapters/mcp/{tools,identity}                         一份工具定义、认证身份
adapters/http/api.py                                  人类入口、只读账本
web/                                                  同源 HTTP 工作台
```

仓储契约按 Workspaces、Requirements、Knowledge、Context、Feedback、Governance、Audit 划分；`SqliteTransaction` 只组合这些仓储并由 Unit of Work 提供同一事务，不承载业务 SQL。只读账本是查询投影，不是第二真实源。

## 数据不变量与事务

Task 保留六状态；用户明确选择：`paused/released` 不接受最后一条 Requirement 归档，必须先回到允许状态。Requirement 保留不可变原文及版本快照，完成摘要归档后退出活跃上下文；最后一条归档在同一事务中完成 Task 并停用短期规则。Agent 在当前 Task 中创建草稿 Rule，宿主主动上报的两次独立成功测试需覆盖 Rule 作用域且无反证，才可激活；CodeNeuro 从不执行测试，也不把报告冒充 Hub 验证。语义内容改变会重置证据版本。Agent 只能晋升当前 Task 活跃版本的短期 Rule，复制条款/范围/优先级并停用来源；修改既有长期契约必须形成提案，只有人类身份可按目标版本审阅批准。审计与所有状态变更同事务写入。

JIT **不持有 SQLite 写锁执行匹配与渲染**：短只读快照取得项目规则修订、Task 修订和会话知识修订 → 纯装配 → 短写事务重验三修订、原子写 Delivery/版本引用/审计。版本变化有界重算，不能让新 P0 漏入旧快照。预览不生成凭据；P0 不因预算、分类或已知确认被折叠；0 分只对本会话该版本简写，不进入效用均分。项目数据库位于 Hub 单机，远程客户端不共享网络盘 SQLite WAL。

## 入口与信任边界

MCP 的核心六动作与列 Task、会话及 Issue 辅助工具在**同一个工具目录**定义，stdio 与认证 streamable HTTP 只改变身份来源。`Actor` 来自 operator 控制的 Token，不信任模型自报权限；Token 具项目边界，会话绑定 actor、项目、Task 和稳定的 Worktree ID；机器、分支、仓库身份为客户端声明，不等同 Hub 验证。标准 MCP 不自动拦截宿主文件/测试工具，CodeNeuro 不执行编码测试。远端工作区路径只是客户端证明，Hub 仍校验词法路径和项目会话范围，不声称访问过客户端磁盘。Web API 调用相同用例；Vue 只读取账本投影，不维护独立规则状态。

## 数据升级与切换

运行时只接受显式 Alembic 新 schema，不自动改写旧数据库。迁移命令无默认生产路径；现行白皮书没有要求维持旧库在线兼容或把历史实验样本搬入新库。旧数据保持原状，若所有者今后确需迁移，应另行授权独立导入与核对，不能让生产启动偷写旧库。Code Graph、指定 LLM 提供方及多仓库配额属于可选增强/历史验收计划，不是中央知识库、需求生命周期与通用 MCP 的切换前置。真实跨机器部署和模型分析效果如未实测，必须明确列为未验证。

验收覆盖领域/并发回滚、Alembic 初始化与旧库拒绝、真实 stdio/HTTP MCP、工作台业务交互、跨 Worktree 隔离；其他真实模型和长程 Agent 的评价只有实际运行后才能宣称完成，不用模拟 provider 或绿色单测代替。
