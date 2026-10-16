# Task 与 Requirement 的 MCP CRUD

Task 使用 `codeneuro_task`，Requirement 使用 `codeneuro_requirement`。两者均使用 `action=create/list/get/update/delete`；状态变化属于 update，不增加 archive/reopen 等工具或动作参数。

## 参数

| 参数 | Task | Requirement | 规则 |
| --- | --- | --- | --- |
| `project_id` | 必填 | — | Task 所属项目 |
| `task_id` | — | 必填 | Requirement 所属 Task，无需 Session |
| `action` | 必填 | 必填 | create / list / get / update / delete |
| `id` | 条件必填 | 条件必填 | get/update/delete 的目标对象 ID |
| `expected_version` | 条件必填 | 条件必填 | update/delete 使用查询结果中的 version |
| `changes` | 条件必填 | 条件必填 | create/update 的类型化字段对象，不接受未知字段 |
| `reason` | 条件必填 | 条件必填 | update/delete 的非空变更原因 |
| `request_id` | — | 可选 | 仅 create 使用，在项目内去重需求录入；重试必须保持同一 Task 和初始原文 |

Task 的 changes 支持 `title`、`description`、`status`。create 要求非空 title，默认 status=active，允许 draft；update 可同时修改元数据与状态。

Requirement 的 changes 支持 `text`、`status`、`summary`。create 要求非空 text，初始状态为 active，不接受完成摘要。update 可以修订正文，也可以修改状态和归档摘要；active 状态没有完成摘要。

查询时不要附带变更参数；delete 不接受 changes。MCP 中 Task 与 Requirement 都返回 `version`；Task 数据库/Web 的 revision 由 MCP 映射为 version，不要求调用方了解内部命名。

## 示例

新建 Task：

```json
{"project_id":"p","action":"create","changes":{"title":"退款处理"}}
```

查询 Task 列表：

```json
{"project_id":"p","action":"list"}
```

重新打开归档 Task（version 为示例，须使用查询结果）：

```json
{"project_id":"p","action":"update","id":"task-id","expected_version":7,"changes":{"status":"active"},"reason":"继续未完成的工作"}
```

修订需求正文：

```json
{"task_id":"task-id","action":"update","id":"requirement-id","expected_version":2,"changes":{"text":"修订后的验收要求"},"reason":"补充验收条件"}
```

归档需求：

```json
{"task_id":"task-id","action":"update","id":"requirement-id","expected_version":3,"changes":{"status":"archived","summary":"已完成并验证"},"reason":"确认完成"}
```

重新打开需求：将上例的 changes 换成 `{"status":"active"}`，携带最新 version 和原因；所属 Task 必须为 active/testing。

软删除需求：

```json
{"task_id":"task-id","action":"delete","id":"requirement-id","expected_version":4,"reason":"撤销该需求"}
```

读取需求及版本历史：

```json
{"task_id":"task-id","action":"get","id":"requirement-id"}
```

## 生命周期与历史

- Task 的暂停、恢复、发布、归档、重开均通过 status 更新，并遵循现有状态机。paused 只能回到暂停前的状态；有活跃需求时不能发布或完成 Task。
- Requirement 正文修订产生新版本。初始 original_text、各旧版本、已签发 Delivery 不变；新的 get_context 使用当前活跃版本。
- 归档需求仍停用关联短期规则，最后一条活跃需求归档仍自动完成 Task。重开只恢复明确选中的对象，不恢复其他需求或规则。
- delete 是软删除，标记为 deleted。list 隐藏已删除对象；get 仍可读取记录，Requirement get 同时返回 history。deleted 不能通过普通 update 恢复。
- 删除 Task 保留子需求记录，但其内容退出正常列表和活跃上下文；删除需求不等于完成需求，不自动完成 Task。相关短期规则停用，历史引用不删除。
- start_session 只负责创建会话和绑定 active/testing Task，恢复为原有参数。Task/Requirement CRUD 不依赖会话，避免为管理记录而启动会话。

## 更新部署

本改动移除旧的 Task 创建/列表、需求提交/列表/归档/恢复 MCP 工具，不保留重复别名。宿主须刷新工具目录。

数据库新增迁移 `3d5f9b7c012e`：扩展 deleted 状态、增加 current_text 并从原文初始化；原文、历史版本和外键引用保留。更新运行环境时须先按授权执行显式迁移，再启动新版本；应用启动不会自动修改数据库。
