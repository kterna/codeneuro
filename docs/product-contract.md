# CodeNeuro 现行产品契约（重构基准）

本文件用于决定代码应当存在什么，而非解释旧模块为何存在。最近的用户决策优先于 `requirements-coverage-2026-10-07.md`、`requirements-coverage-2026-10-08.md` 和旧实验手册中冲突的实现路线；历史审计仍作为来源，不再直接充当验收清单。

## 职责边界

- CodeNeuro 是宿主无关的知识与任务服务：中央数据库是规则和需求的唯一真实源；Hub 向多个 worktree 提供一致的 MCP/HTTP 能力，工作台直接打开、无需鉴权；服务默认仅监听本机，不应将无鉴权端口暴露公网。不同机器不共享网络盘 SQLite 数据库。
- Coding Agent 自行在本地以正则为核心检索 Task 标题、描述，决定复用或新建；多候选不能被服务擅自绑定。MCP Task 列表按 ID 游标分页，默认 20 条，支持状态过滤；省略过滤仍包含历史状态。标题/描述分别限 200 字符并显式标记截断，完整内容通过 get 获取；不得因摘要未匹配就断言完整正文无匹配。语义分析仅可增强，失败必须明确呈现。
- Agent 编码、读写文件、运行测试并对结果负责。CodeNeuro 不包装、不拦截这些宿主工具，不提供编辑/测试执行型 MCP 工具。宿主主动上报的证据必须标为宿主报告。
- 不包含按宿主品牌分支的核心实现、NativeBridge、静态规则副本、导出或 `sync --watch`。不支持 MCP 的宿主若需要适配，应由宿主侧独立项目实现；CodeNeuro 不暗示标准 MCP 会自动拦截文件操作。

## 核心行为

- Project、Topic、Worktree、Task、Requirement、Rule、Finding、Session、Delivery、Feedback 各有明确身份；Requirement 初始原文和历史版本不变，当前正文允许按版本修订；当前 Task 的活跃需求按最新版本在独立需求区下发，不受规则等级筛选隐藏，不伪装成长期 Rule。
- Agent 带预期版本和完成摘要归档 Requirement 后立即退出活跃上下文；最后一条需求归档自动完成 Task。无 Requirement 的历史 Task 仍可人工完成。归档关联短期 Rule 的停用、Task 状态和审计同事务提交。
- 任务状态流转契约：支持 draft、active、testing、released、archived 与 paused。draft 可流转至 active/archived；active 可流转至 testing/archived，或进入 paused；testing 可流转至 active/released/archived，或进入 paused；paused 须先经恢复操作回至暂停前的 active 或 testing，不直接跨态流转；released 可回退至 active 或完成 archived；已归档 (archived) 任务可按预期 revision 和原因直接重新激活至 active，保留原 Task ID，也仍允许人工进一步流转至上线 (released)。Agent 经用户授权通过 Task CRUD 的 `update` 和 `changes.status` 修改状态；`start_session` 只创建会话并绑定 active/testing Task，不承载任务更新参数。上述操作都不自动恢复历史需求或已停用规则。
- 对 active/testing Task，可按预期 version 和原因恢复指定的已归档 Requirement：保留 ID 和原文，新增 active 版本并清空当前完成摘要，历史归档版本及摘要保持不变。其他需求和已停用 Rule 均不自动恢复；恢复的需求重新进入活跃上下文。需求版本、Task revision 和恢复事件同事务提交。
- Task 与 Requirement 的 MCP 操作分别收敛为 `codeneuro_task`、`codeneuro_requirement`，共用 `action=create/list/get/update/delete`、`id`、`expected_version`、`changes`、`reason`。MCP 返回统一 `version`；Task 内部和 Web 仍使用 revision。正文修订、归档、重开统一为 update，不使用专用 reopen 参数。更新/删除需当前版本及原因，需求新建可通过 request_id 去重。
- Task/Requirement 的 delete 均为软删除（deleted）：退出正常列表和活跃上下文，保留记录、版本、引用及既有下发，get 仍可读取。删除 Task 不改写其需求记录，但隐藏其下属活跃内容并停用短期规则；删除 Requirement 停用关联规则，不把删除视为需求完成，不自动完成 Task。deleted 为终止状态，不通过普通 update 恢复。
- Requirement 的 update 可修订 text、status、summary；每次成功写入新增版本，初始 original_text 与旧版本/Delivery 不改写。get 同时返回版本历史；Task 标题、描述和状态可通过 update 修改。
- 当前 Task 的活跃短期 Rule 可由 Agent 按版本晋升：保持条款、范围、优先级，不扩大权限；来源失活，晋升记录和审计同事务提交。修改现有长期契约仍需人工审阅。
- JIT 必须显式提供精确的 P0–P3 等级集合，无默认、阈值或自动补 P0。有主题时主题决定准入，文件仅辅助排序；无主题才按文件匹配，允许真实无路径规则和纯业务查询。全局性由 `is_global` 显式表达，仍受等级和 Task 可见性约束；已经准入的 P0 才具有全文/预算保护。旧 category/categories/min_priority 删除。
- Topic 为项目级受控词表，支持显式 CRUD、版本和目录修订；稳定 key 不可改/复用，引用后业务边界冻结。删除被活跃/草稿 Rule、未审阅 Finding、未决 Proposal 阻断，不级联摘除引用或自动重分类。项目分类完成人工确认后开启主题查询，详见 [v2 契约](topics-v2.md)。
- Rule 检索范围与验证证据解耦：测试计划绑定条款、检查 ID、宿主测试 ID 和规则版本；规范条款走人类版本审阅。没有“任意同 Task 成功测试即放行”的路径，Hub 不执行或保证测试真实性。
- 未审阅 Finding 仅在同一活跃 Task 内按主题/文件提示，允许可选路径、显式重分类/结束，不跨任务自动变成 Rule。热路径不调用模型或自动裁决。
- 实际下发保存协议版本、规范化查询、目录修订、匹配依据及规则/需求版本凭据；旧回执不重算；预览不计数。MCP 仅返回一份 JSON 文本，get_context 通过 markdown 提供正文并保留版本引用和元数据，不重复输出 sections；完整 sections 继续保存在 Delivery 中。max_chars 约束 Markdown 而非最终 JSON 体积，保持已准入 P0 全文保护。评分必须引用实际下发，`0=已知、1=无关、5=核心需要`，效用均分排除 0。写入按版本并保持请求幂等，跨项目/Task/Worktree 不串数据。
- 可选代码索引、PRD/语义分析与任务提炼走有界异步工作流，结果带证据位置和失败状态，不得冒充确定性推导或自动批准长期规则。
- Web 工作台通过相同业务用例支持任务重开、需求录入/归档/指定恢复、既有契约的人类审阅、规则作用域密度、活跃任务与资产演进账本；UI 不是规则的第二真实源。代码焦点浏览如要做，必须依赖真实索引，而不是伪造远程文件树。

## 目标架构与约束

```text
MCP stdio / Hub MCP HTTP / Web HTTP / CLI
                  │ 参数映射；不持有业务规则
                  ▼
应用用例：任务和需求 / 规则治理 / JIT 与反馈 / 可选智能工作流
                  │ 统一状态转换、版本及事务边界
                  ▼
领域实体与纯规则：状态、范围、预算、来源与不变量
                  │
                  ▼
持久化：单一数据模型、事务、查询和迁移
```

远程工作区路径在客户端解析及确认；Hub 不将 Windows 路径当服务器本地路径。JIT 的候选选择与渲染不访问网络 LLM。所有 MCP 入口必须暴露一致的核心语义；Web 与 MCP 只做参数适配，不得复制业务实现；无鉴权时不能核实人工审阅者的真实身份。删除旧架构时只继承被本契约认可的行为和必要历史数据，不以旧类名/表名作为设计输入。

## 验收与尚未证明的事项

以单元、并发回滚、版本幂等、真实 stdio/HTTP MCP、无凭据远程协议、直接打开 Web 的浏览器流程与迁移测试组成同一行为验收矩阵。真实外部模型、真实 Agent 长任务、跨机器部署和负载基准另需实证，不能用模拟 provider 或协议测试替代。旧 R09 宿主钩子及 R10–R11 静态规则同步不再作为产品验收项；其余旧条目需按本契约重新核对，而不是机械照搬旧实现。
