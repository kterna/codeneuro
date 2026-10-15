# CodeNeuro 架构与约束

产品规则以 [现行产品契约](product-contract.md) 为准。CodeNeuro 是一个模块化单体：领域策略不依赖数据库或 MCP；跨模块业务由工作流在一个 Unit of Work 内协调；仓储按 Workspaces、Requirements、Knowledge、Topics、Context、Feedback、Governance 与 Audit 分工；HTTP/Web 和 MCP 只做 DTO 映射，不要求 Token。源码位于 `src/codeneuro/`，不存在需长期并行维护的 `codeneuro_rebuild` 包。

```text
Web/Vue ──► HTTP API ─┐
stdio MCP ────────────┼──► 工作流 ─► 领域策略
streamable HTTP MCP ──┘       │
                              ▼
                       Unit of Work / SQLAlchemy Core
                              │
                       Hub 本机 SQLite WAL
```

## 主要实体

- Task 六态；Requirement 独立保存原文、归属、归档摘要及不可变版本快照。最后一条活跃需求归档在同一事务中完成 Task、停用短期规则；`paused/released` 拒绝归档。
- Rule 区分任务临时规则和项目长期契约。`rule_versions` 保存不可变历史；晋升复制有效版本为新长期 Rule，保留来源版本和理由。对既有长期契约的更新须 Agent 提案、人类按版本审阅。
- Topic 使用项目内稳定 key、定义锁定和目录修订；当前关联使用同项目复合外键，版本快照存 JSON。CRUD 与知识引用/删除保护处于同一写事务。
- Session 固定调用来源标签、项目、Task 和客户端声明的 Worktree；标签不构成身份鉴别。Delivery 记录实际输出及 Rule/Requirement/Finding 版本；反馈引用本会话真实下发。0=已知仅简写该会话版本，已适用且被等级集合选中的 P0 保持完整。
- 未经审阅的 Finding 保持任务作用域：同任务跨会话按主题/路径匹配提醒，注明未审阅；不跨任务下发，也不自行变成长期规范。宿主上报的测试报告标记为 `client_reported`，测试计划逐检查满足两个独立成功证据和无反证等条件才可激活任务草稿；规范计划须人类固定版本审阅，测试路径与检索范围独立；CodeNeuro 不执行测试。

## JIT 并发与作用域

短只读快照获取项目规则修订、Task 修订、会话已知修订及主题目录状态，释放数据库读事务后纯装配，最后短写事务重核修订并原子签发 Delivery；冲突有界重算，不签发旧快照/新版本混合结果。先按项目、Task、活跃状态、显式等级集合及主题/路径适用性准入；有主题时路径只辅助排序，没有主题才按路径准入；`implementing/debugging` 决定同优先级内顺序，清单与详细模式均保留条款。结果同时给出 Markdown 和 `must_obey_contracts`、`task_actionable_checklist`、`module_gotchas` 结构化章节。P0 不绕过等级和适用性，但准入后不因预算或已知反馈消失；省略项分别报告。

语义模型不是 JIT 热路径的依赖。当前未配置语义评估时返回 `not_assessed`；Agent 主动上报的潜在冲突只有涉及的规则 ID/版本都仍在本次候选时才以“未验证报告”形式提示，**不冒充模型诊断或自动仲裁**。不把相似文本机械合并。账本上的“密度”由已存 Rule 的具体作用域前缀计算，不暗示服务器扫描过远程文件树。

## 数据与部署

schema 由初始迁移 `1f7a79740655` 和 v2 后继 `2c4e8a6b901d` 管理；迁移必须由所有者显式选定目标，新库初始化及版本升级共用同一迁移链。旧库升级先在隔离副本验证，项目分类确认后才启用主题查询；历史 category 仅留在 v1 快照，当前规则不保留兼容分类。运行入口拒绝旧版或未知 schema，不对真实旧库做隐式写入。Web、同机 stdio MCP 与远程 HTTP MCP 使用 Hub 本机同一数据库。远程机器不能在网络共享盘直接打开 SQLite WAL；服务将工作区路径视为客户端的有界声明；JIT 对文件参数做工作区相对路径校验，并执行项目/Task/会话一致性检查，不声称做了远端 OS 文件验证。

v2 的 CRUD、查询真值表、证据、接口和迁移验收见 [主题升级契约](topics-v2.md)。更多工程边界见 [实现规范](rebuild-plan.md)。历史 R01–R31 清单及旧架构交付记录不是当前入口代码的规范；已取消的宿主专用钩子、静态副本及 CodeNeuro 代跑测试能力不会恢复。
