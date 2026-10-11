# 任务规则自治与长期契约审阅

Agent 通过标准 MCP `codeneuro_create_task_rule` 在绑定的 Task 中创建草稿；草稿不进入 JIT。宿主实际运行测试后，可通过 `codeneuro_report_test` 上报 argv、相关相对路径、退出码及带时区的起止时间。CodeNeuro **只记录客户端报告**，不执行测试；Hub 记录接收时间用于阻止旧报告验证新条款，重复事件不能通过换请求 ID 伪造独立证据。

使用 `codeneuro_observe_rule` 将报告关联到规则当前证据版本，相关测试必须覆盖规则作用域；失败的测试不能作为支持。两份不同成功证据、无反证、有效证据置信度不低于 0.6 才能 `codeneuro_mutate_task_rule(action="activate")`。修改条款或升级优先级使规则回到草稿并重置证据；降级优先级和状态变更不声称旧测试验证了新内容。规则状态、不可变版本快照、来源和审计同一事务写入。

`codeneuro_promote_rule` 仅对当前 Task 的活跃短期规则按版本原样复制为长期契约；源规则退出活跃下发，保存来源版本与原因。修改已有长期 Rule 时，Agent 调用 `codeneuro_propose_contract`，Web 人类身份对具体版本作批准/拒绝。批准时版本已变则冲突，不自动合并或擅自扩大范围。

`codeneuro_archive_requirement` 由 Agent 确认实际工作完成并提交摘要；CodeNeuro 不核验代码或运行测试。当前 Requirement 关联的活跃短期规则随即失活，最后一条活跃需求归档时 Task 完成并停用剩余短期规则。暂停或已发布状态需先按确定的状态流程处理，不允许悄悄跳转。Web 人类审阅与 MCP 业务命令使用同一工作流；`0=已知`反馈仅对本会话/版本简写，不降低 P0。
