# v2：受控主题、显式等级与独立验证

本文定义当前源码的破坏性升级契约，不代表迁移、测试、前端构建或生产切换已经执行通过。初始版本 `1f7a79740655` 的后继迁移为 `2c4e8a6b901d`；运行入口仍只检查版本，不隐式升级数据库。

## 查询协议

```python
codeneuro_get_context(
    session_id="...",
    priorities=["P0", "P1"],  # 必填、非空、不重复，只能 P0–P3
    topics=["volume-revision"],
    # files=["backend/Controller.java"],  # 可选，不用虚位文件
)
```

- `category`、`categories`、`min_priority` 已删除，不保留参数兼容层；MCP 拒绝未声明参数，不静默忽略旧筛选条件。
- `priorities` 是精确集合，不是阈值。`["P1", "P3"]` 不包含 P0/P2；服务端不自动追加 P0。
- `files` 与 `file_path` 二选一；`topics` 缺省与空数组等价。主题和文件不能同时为空。
- 每次先执行项目、Session、Task、活跃状态和等级选择，再判定业务适用性：

| 查询条件 | 非全局规则的准入 | 路径的作用 |
| --- | --- | --- |
| 有 topics，无文件 | 主题有任一交集 | 无 |
| 有 topics，也有文件 | 主题有任一交集 | 仅辅助排序，不额外扩召回 |
| 无 topics，有文件 | 文件命中 patterns | 准入及排序 |
| 均为空 | 参数错误 | 不回退成全项目查询 |

`is_global=true` 显式声明全局适用，但仍受所选等级、状态及 Task 可见性约束。空路径/空主题不隐式等于全局。P0 不是全局标记。

已准入的 P0 完整下发，不因字符预算或已知反馈折叠；未选中的/不适用的 P0 不下发。非 P0 同会话同版本 `score=0` 可简写。效用分不改变优先级或主题。

P0 表示严重红线并要求 `priority_reason`；P1 为核心业务约束，P2 为标准实践，P3 为参考建议。取消的是查询等级默认值，规则创建仍可默认 P1。

当前 Task 的活跃 Requirement 继续作为独立需求区下发，不被规则等级集合隐藏；预算省略必须记录。Finding 仍为同 Task 未审阅观察，按主题/文件和选定等级匹配，不会自动成为 Rule。

## Topic 生命周期与 CRUD

```text
Topic(project_id, key, name, description, version,
      status=active|deleted, definition_locked)
```

- `key` 为项目内唯一的小写 slug（最多 64 字符），创建后不可改；逻辑删除后也不复用。
- `name` 为显示名，`description` 为业务边界，不是任意标签。创建须显式操作及理由，不随规则创建自动登记。
- 从未引用时可以修改名称/边界；第一次被 Rule、Finding 或 Proposal 引用时锁定边界，并增加 Topic 版本和目录修订。
- 已锁定边界不能改义，只能改显示名；语义变化需新 Topic，并走知识对象自己的版本化重分类流程。
- 改名不增加 Rule 版本，不令其测试证据失效，也不改写历史 Delivery。
- 删除采用 `expected_version` 乐观锁，同一写事务检查活跃/草稿 Rule、未审阅 Finding 和待处理 Proposal。任何阻断返回 `topic_in_use` 和有界引用摘要。
- 没有强删、级联摘除、自动转移、恢复、合并或别名。历史规则快照和已签发回执保留；新查询引用已删除/未知主题时报错，不回退文件/全量模式。
- 写操作、引用校验、定义锁定、目录修订、关联写入及审计同事务；SQLite 写事务使用现有串行化边界，避免删除检查后被插入新引用。

MCP 读操作显式给项目，写操作从活跃 Session 推导项目：

```python
codeneuro_create_topic(session_id, key, name, description, reason)
codeneuro_list_topics(project_id, query="", include_deleted=False, cursor=None, limit=50)
codeneuro_get_topic(project_id, key, include_usage=False)
codeneuro_update_topic(session_id, key, expected_version, reason, name=None, description=None)
codeneuro_delete_topic(session_id, key, expected_version, reason)
```

列表默认只含活跃主题，按稳定 key 游标分页，支持 key/名称搜索；每页最多 100 项。`include_usage` 返回 `can_delete`、当前阻断计数及每类最多 20 个引用；历史引用并不构成当前删除阻断。

HTTP 人类入口共用上述工作流：

```http
GET    /api/projects/{project_id}/topics
GET    /api/projects/{project_id}/topics/{key}
POST   /api/projects/{project_id}/topics
PATCH  /api/projects/{project_id}/topics/{key}
DELETE /api/projects/{project_id}/topics/{key}
POST   /api/projects/{project_id}/topics/enable
```

修改/删除携带 `expected_version` 与理由；启用携带 `expected_revision` 与人工确认理由。复用现有信任边界，没有新增鉴权系统：人类入口的角色区分不代表能验证操作者真实身份。

`start_session` 附带协议版本和最多 30 项的主题目录、`taxonomy_revision`、分页游标及启用状态。Agent 优先复用该目录，不必每次查询前先列主题；截断时再按需搜索。

## 检索范围与验证证据解耦

新 Rule 要显式提供 `topics` 和 `validation_spec`。非全局规则至少有一个合法主题；`patterns=[]` 为真实无路径规则，无需 `_meta/**`。

可测试规则声明每条条款对应的检查及宿主测试 ID，条款索引从 0 开始：

```json
{
  "kind": "test",
  "checks": [
    {"id": "invalidate-pointer", "clause_indexes": [0], "test_ids": ["VolumeRevisionIT#invalidate"]}
  ]
}
```

宿主上报：

```json
{
  "test_cases": [{"test_id": "VolumeRevisionIT#invalidate", "status": "passed"}],
  "paths": []
}
```

`codeneuro_observe_rule` 必须提供 `check_ids`。报告须覆盖该检查声明的测试 ID；失败/跳过的测试不能支持规则。激活既检查总证据，也逐检查要求两份独立成功报告、无反证及有效置信度至少 0.6。仅“同一个 Task 的成功测试 + reason”不构成覆盖。原有 Session/版本约束、Hub 接收时间、新内容不可引用旧报告、重复事件幂等仍保留。

无法测试的规范采用 `{"kind":"review","basis":"明确规范依据"}`。人类通过 `POST /api/projects/{project_id}/rules/{rule_id}/review` 审阅固定草稿版本；不能用人工按钮替代 `kind=test` 的测试证据。测试始终为 `client_reported`；Hub 不执行命令，也不保证客户端真实性。

条款、标题、主题、路径、全局声明、验证计划改变或优先级升级，会增加规则版本、退回草稿并重置证据。主题显示名变化与规则语义变化分离。

## 知识维护和长期契约

- `codeneuro_update_finding(session_id, finding_id, expected_version, reason, topics=None, resolve=False)` 明确重新分类或结束观察；HTTP 对应 `PATCH /api/projects/{project_id}/findings/{finding_id}`。不能通过删 Topic 自动清掉 Finding。
- 修改普通 Task Rule 仍用版本化 `mutate_task_rule`；修改既有长期契约用固定候选：

```python
codeneuro_propose_contract(
    session_id, target_rule_id, expected_target_version,
    candidate_rule_id, expected_candidate_version, reason,
)
```

候选必须属于当前 Task。可测试候选先完成声明验证并激活；规范候选接受人类提案审阅。批准时重核目标/候选的项目、版本、状态、关联 Requirement 和证据；采用候选语义后停用候选。v1 文本式提案可保留或拒绝，但不能直接批准，需重新提交。

晋升只原样复制当前活跃版本的条款、主题、路径、全局声明、等级和验证依据，保存来源版本；不借晋升扩范围。

## 数据迁移与按项目启用

新增 `project_topics`、`rule_topics`、`finding_topics`、`rule_reviews`。当前关联使用同项目复合外键，版本快照使用 JSON。当前 `rules.category` 删除，旧 `rule_versions` 和旧提案中的 category 仅用于历史追溯，以 `schema_version=1` 标记；新快照为 v2，不回填或篡改旧分类。

升级不猜测主题，不把 `business/security/gotcha` 直接变成业务主题。升级后：

1. 所有项目 `topic_query_enabled=false`；可继续使用新接口的文件查询，但仍必须显式传等级。
2. 显式建立主题，逐条核查活跃规则的主题、全局性、真实路径、P0 理由及验证依据。
3. 未分类旧规则由人类通过 `POST /api/projects/{project_id}/rules/{rule_id}/classify` 固定版本、重新确认规范依据；不伪造测试证据。已有验证计划的规则不能借该入口绕过正常治理。
4. 对未审阅 Finding 分类或明确结束；通过覆盖检查后，人类按目录修订启用项目主题查询。
5. 老 `**` 在文件模式仍可能过度召回，必须人工治理，不声称主题算法自动消除此问题。

迁移用显式事务重建 SQLite 表，事务开始前关闭 FK，提交前执行 `foreign_key_check` 和 `integrity_check`，最后恢复 FK。不得把“脚本已编写”称为“已验证安全”；上线前必须在隔离副本验证行数、快照、回执、反馈、索引/约束、P3 写入和回滚。不提供有损 downgrade，失败恢复使用已核验备份。

批量导入同样采用 v2。主题必须预先登记，或在独立 `topics` 段中声明 `{project_id,key,name,description}`；不从 Rule/Finding 的键推导定义，不覆盖同名不同义的已登记主题。Rule 需明确规范审阅依据，禁止导入器伪造测试。preflight 先核对身份、主题与不可变快照，再在同一事务写入；旧 category 载荷明确拒绝。

Delivery v2 保存规范化查询、协议版本、目录修订、解析后的主题、匹配依据、实际版本及省略/超预算信息。请求指纹含协议版本，旧 request_id 不能被新查询静默复用；历史回执按原内容读取，不重新计算或改写。

## 必须实际执行的验收

- 纯 `git-workflow` 查询，无虚位文件；任意类文件配 `volume-revision` 召回跨层规则。
- `frontend-layout` 不被签章/Git 的旧 `**` 绕过；文件模式如实保留其旧路径语义。
- 缺失/空/重复等级报错，P3 可写入和展示，未选 P0 不自动追加；选中且适用的 P0 不裁剪。
- Topic 重复键、跨项目、陈旧版本、锁定边界、引用阻断、审计失败回滚及并发更新。
- 空路径测试规则按声明测试项激活；任意无关成功报告、跳过项、部分检查、旧版本证据不能放行。
- 规范审阅、候选提案漂移、失活/归档 Task 和 Requirement 边界。
- 新库初始化与已有版本副本升级，完整性、历史快照/回执/反馈及索引约束。
- Web Topic CRUD、存量分类、Finding 处理、P3、无默认等级预览、前端类型检查/构建。

现有测试加 `tests/test_topics_v2.py` 是待执行的验收资产，不是通过证明。
