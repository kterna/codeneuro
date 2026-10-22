# MCP 与 HTTP 资源

所有 MCP 工具返回一段 JSON 文本，拒绝未声明参数。直接使用项目、父需求、Task 或实际记录 ID；没有 Session 生命周期或产品协议选择参数。

## Requirement / Task CRUD

共同动作：`create/list/get/update/delete`。更新和删除必须给出 `id`、`expected_version`、非空 `reason`；传入的是本次要修改的 `changes`，未传字段保持原值，显式 null 与未知字段会被拒绝。

| 参数 | Requirement | Task |
| --- | --- | --- |
| project_id | 必填 | 必填 |
| requirement_id | 不使用 | create 必填；list 可按父需求筛选 |
| changes.title | 创建必填 | 创建必填 |
| changes.text | 创建必填，整体目标 | 不使用 |
| changes.description | 不使用 | 本任务实现范围 |
| changes.acceptance_criteria | 整体验收要求 | 本任务验证要求 |
| changes.status | draft/active/accepting/completed | draft/active/testing/paused/completed |
| changes.completion_summary | 整体验收结论 | 不使用 |
| changes.verification_summary | 不使用 | 独立验证方式与结果 |
| changes.verification_report_ids | 不使用 | 可选的本 Task 成功报告 ID |
| changes.archived | 归档/恢复，布尔值 | 归档/恢复，布尔值 |

创建默认 active；draft 父需求仅接受 draft 子任务。Task 不能通过 update 改换父需求。删除为软删除，不接收客户端设置的 deleted_at；有未删除子任务的需求不能删除。完整状态规则见[需求与任务](requirement-task-hierarchy.md)。

```python
codeneuro_requirement(project_id="archive", action="create",
    changes={"title": "档号要素维护", "text": "整体业务目标"}, request_id="create-goal")
codeneuro_task(project_id="archive", action="create", requirement_id="返回的需求ID",
    changes={"title": "全宗号", "description": "独立实现范围", "acceptance_criteria": "验证要求"})
```

list 返回 `items/next_cursor`，默认 20 条、最大 100 条；文本摘要最多 200 字符，并返回 `truncated`。默认包含非删除的归档记录，可用 statuses 筛业务状态。游标必须沿用相同项目、资源、父需求与状态筛选；筛选变化应重新开始列表。

get 返回完整当前内容和分页修订历史；`history_cursor` 是上次最后修订号，`history_limit` 默认 20。软删除记录仍能通过 get 查到。source 可选提供 workspace、machine_name、platform、repo_identity、git_branch，仅作来源声明。

## 上下文、下发和反馈

```python
codeneuro_get_context(project_id="archive", task_id="明确选中的任务ID",
    priorities=["P0", "P1"], files=["src/ArchiveService.java"],
    situation="准备提交本次改动")
```

`files` 与 `file_path` 二选一；必须有真实相对文件或已登记 topics。priorities 是明确集合，不是阈值。`situation` 是一句当前在做什么，只被记录，不参与筛选。`max_chars` 默认 24000，范围 512–200000，约束完整条款与头部；`budget_exceeded` 在追加按需目录前计算。目录不受此预算或单独的总字数上限限制。`intent` 为 implementing/debugging，`mode` 为 detailed/checklist。

规则声明为 card 时，本次匹配到的所有目录项均进入 `markdown` 和 `rule_refs`，每项给出规则编号、版本、标题和使用时机，不包含正文。目录提示不是当前要求，不能凭提示推断完整条款。Agent 根据当前任务及下一步操作自主选择相关项，调用 `codeneuro_open_rules(delivery_id, rule_ids, reason)` 读取正文，不要求用户逐条选择，不默认加载无关正文。一次可读取 1–20 个不同编号；返回该次下发记录的版本，重复调用不重复记录取用。目录下发与实际读取分别记录，读取本身不扩大操作授权。

Task 查询包含父需求和本任务，不带入兄弟内容；项目级查询不推导 Task。结果含正文、实际引用、查询、匹配依据与省略信息，不重复返回 sections。

相同项目、操作和 request_id 的相同输入重放原响应，变更输入冲突；省略或更换 ID 获取当前知识。`codeneuro_get_delivery(delivery_id)` 直接读取保存的完整 JSON，不重新计算，也不裁剪 sections 等已存字段；它与精简的新上下文输出不同。迁入的旧下发正文仍是原始记录，其中旧字段不会用于当前上下文装配。

`codeneuro_rate_rule(delivery_id, rule_id, score, reason)` 只接受真实下发的规则；score=0 是已知统计，不隐藏未来正文。`codeneuro_report_issue(project_id, issue_type, title, description, ...)` 可选 Task；conflict 必须指定 Task 和至少两条不同规则。两者没有 debug 前置。

## 工具目录

| 范围 | 工具 |
| --- | --- |
| 项目 | codeneuro_list_projects |
| 需求/任务 | codeneuro_requirement、codeneuro_task |
| 上下文 | codeneuro_get_context、codeneuro_get_delivery、codeneuro_open_rules |
| Task 规则 | codeneuro_create_task_rule、codeneuro_mutate_task_rule、codeneuro_promote_rule、codeneuro_propose_contract |
| Task 验证 | codeneuro_report_test、codeneuro_observe_rule |
| Task 观察 | codeneuro_record_finding、codeneuro_update_finding |
| 项目主题 | codeneuro_list_topics、codeneuro_get_topic、codeneuro_create_topic、codeneuro_update_topic、codeneuro_delete_topic |
| 反馈 | codeneuro_rate_rule、codeneuro_report_issue |

规则、验证和观察写操作显式提供 task_id；Topic CRUD 显式提供 project_id。具体规则证据要求见[治理说明](governance.md)。

## HTTP 资源

```text
/api/projects/{project_id}/requirements
/api/projects/{project_id}/requirements/{id}
/api/projects/{project_id}/requirements/{id}/tasks
/api/projects/{project_id}/tasks
/api/projects/{project_id}/tasks/{id}
/api/projects/{project_id}/requirements/{id}/versions
/api/projects/{project_id}/tasks/{id}/versions
/api/projects/{project_id}/deliveries/{delivery_id}
```

列表使用 GET；创建 POST body 为 changes、可选 request_id/source，Task 还需要 requirement_id。修改 PATCH 为 expected_version、changes、reason；DELETE 为 expected_version、reason。HTTP 详情不嵌入历史，用 versions 子资源分页获取。

长期规则停用使用 `POST /api/projects/{project_id}/rules/{rule_id}/retire`，body 为 `expected_version`、非空 `reason`、严格布尔值 `confirmed: true`，可选 `request_id`。返回 `id/project_id/version/status`。这是工作台明确确认入口，不是 MCP 自动治理工具；Task Rule、陈旧修订和非活跃状态会被拒绝。重试须复用相同 request_id 和输入，不修改旧 Delivery 或旧请求结果。

修改长期规则的查询形态使用 `POST /api/projects/{project_id}/rules/{rule_id}/applicability`，body 为 `expected_version`、`delivery_mode`（full/card）、`applies_when` 与非空 `reason`。它不改条款、主题、路径和等级；内容相同时不升版。

账本数组是有界摘要，计数以 `ledger.counts` 为准，后续列表使用返回的游标。Web 与 MCP 共用同一用例，错误按 invalid_request、not_found、conflict、forbidden 区分。服务无鉴权，Web human/MCP actor 都是来源标签。
