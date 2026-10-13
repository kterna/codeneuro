# CodeNeuro 产品审查与验收清单（256 项）

日期：2026-10-12。基线：`c30cd63c20f74c0b52c76d510b24bac0e4cc51a2`。覆盖 20 个分组，从产品业务到 7 个页面、共享交互、视觉、协议、数据与交付。本清单记录审查时的状态，不表示已完成修复。

配套：[完整审查报告](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md)、[证据索引](D:/1/github/codeneuro/docs/audit-2026-10-12/README.md)、[可机器读取的清单](D:/1/github/codeneuro/docs/audit-2026-10-12/checklist-status.json)。

## 判读规则

- **通过**：仅对本项条件及注明的方法成立；只有通过项打勾。代码或文档通过不等同浏览器、实机或规模验证。
- **部分**：有基础实现，但整个条件尚未满足；正文写明边界。
- **缺陷**：存在源码证实或运行复现的问题，链接报告 D 编号。
- **增强**：建议补全的产品能力；不自动当作当前版本必须实现的缺陷。
- **待验证**：缺乏本轮证据，不能判断为通过或失败。
- **范围外**：现行产品契约未要求或已明确取消；不是未完成任务。

每行依次是验收条件、当前结果与证据。相同缺陷可以影响多项条件；32 个独立缺陷不能与未勾选数混为一谈。清单并非等权评分表，不据此计算产品完成百分比。

## 当前状态分布

| 状态 | 项数 |
| --- | ---: |
| 通过 | 115 |
| 部分 | 13 |
| 缺陷 | 84 |
| 增强 | 24 |
| 待验证 | 17 |
| 范围外 | 3 |
| **合计** | **256** |

## 分组导航

| 分组 | 检查项 | 数量 |
| --- | --- | ---: |
| A | [产品定位、职责与业务边界](#group-a) | 12 |
| B | [首次使用、项目建立与项目管理](#group-b) | 12 |
| C | [任务与需求的领域流程](#group-c) | 16 |
| D | [Session、Worktree 与多端协作](#group-d) | 12 |
| E | [JIT 上下文与规则适用性](#group-e) | 16 |
| F | [规则治理、测试证据与晋升](#group-f) | 14 |
| G | [反馈、问题报告与审计闭环](#group-g) | 12 |
| H | [Explorer：规则作用域页面](#group-h) | 14 |
| I | [Tasks：需求与任务页面](#group-i) | 16 |
| J | [Rules：项目规则库页面](#group-j) | 14 |
| K | [Review：长期契约审阅页面](#group-k) | 14 |
| L | [Feedback：规则效用与开发便签页面](#group-l) | 10 |
| M | [Activity：变更审计页面](#group-m) | 10 |
| N | [Settings：项目配置页面](#group-n) | 10 |
| O | [导航、指标、消息与共享交互](#group-o) | 12 |
| P | [布局、视觉层级与样式细节](#group-p) | 14 |
| Q | [键盘与可访问性](#group-q) | 10 |
| R | [API、数据一致性与异常处理](#group-r) | 12 |
| S | [工程测试、构建、备份与发布](#group-s) | 14 |
| T | [实机、规模及明确不纳入本期的范围](#group-t) | 12 |

<a id="group-a"></a>
## A. 产品定位、职责与业务边界

- [x] **A01 · 通过（文档）** 产品明确服务 Coding Agent 的任务、需求和规则上下文管理。当前：README 与现行契约表达一致。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)、[README](D:/1/github/codeneuro/README.md)。
- [ ] **A02 · 部分（代码/运行）** 所有生效资产遵循数据库唯一真实源和统一写入不变量。当前：常规用例成立，批量导入绕过版本和审计。证据：[D31](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d31)、[架构说明](D:/1/github/codeneuro/docs/architecture.md)。
- [x] **A03 · 通过（代码/测试）** 产品不冒充代码编辑器或测试执行器。当前：MCP 工具只记录宿主执行的测试事件。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[MCP 入口](D:/1/github/codeneuro/src/codeneuro/adapters/mcp/tools.py)。
- [x] **A04 · 通过（文档/测试）** 宿主测试证据明确标为客户端报告。当前：client_reported 语义有文档与治理测试支持。证据：[治理说明](D:/1/github/codeneuro/docs/governance.md)、[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **A05 · 通过（代码/测试）** stdio 与 HTTP MCP 具有一致核心工具语义。当前：工具目录一致性及真实协议测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **A06 · 通过（文档）** 接入 MCP 不被宣传成自动拦截宿主读写。当前：README 和接入说明明确要求主动 get_context。证据：[README](D:/1/github/codeneuro/README.md)。
- [ ] **A07 · 缺陷（运行）** 远程工作区声明不会被误读为 Hub 磁盘路径。当前：合成远程声明返回了 Hub 本地标记文件。证据：[D04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d04)。
- [ ] **A08 · 部分（代码/运行）** 项目、任务和工作区归属在所有数据入口保持一致。当前：常规隔离有保障，导入错误回退破坏归属。证据：[D32](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d32)、[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **A09 · 通过（文档）** 操作者标签与真实身份验证边界清楚。当前：无鉴权及不能核实真实审阅者已写明。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。
- [x] **A10 · 通过（代码/文档）** Requirement、Rule、Finding、Delivery 不混作同类实体。当前：核心模型和领域职责有明确划分。证据：[架构说明](D:/1/github/codeneuro/docs/architecture.md)。
- [ ] **A11 · 部分（流程审查）** 录入、执行、反馈、治理、完成和追溯形成可使用闭环。当前：正常主链存在，Issue、证据和历史处理缺口仍在。证据：[G02](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g02)、[G03](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g03)、[G07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g07)。
- [x] **A12 · 通过（文档）** 现行验收基准明确覆盖冲突的历史计划。当前：现行契约明确说明旧钩子及静态同步不再验收。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。

<a id="group-b"></a>
## B. 首次使用、项目建立与项目管理

- [x] **B01 · 通过（运行）** 新数据库通过显式迁移后可启动服务。当前：本轮所有合成数据库按迁移入口初始化。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[专项后端](D:/1/github/codeneuro/docs/audit-2026-10-12/backend-results.json)。
- [x] **B02 · 通过（测试）** 旧版或未知 schema 不被运行时偷偷升级。当前：现有拒绝旧库且不写入的测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **B03 · 通过（浏览器）** 直接打开首页可以进入工作台。当前：现有冒烟与专项浏览器通过正常入口加载。证据：[浏览器冒烟](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **B04 · 通过（浏览器）** 空项目列表提供注册项目入口。当前：已实际创建合成项目并看到空项目视图。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **B05 · 通过（浏览器）** 合法的新项目 ID 和名称可以保存并选中。当前：createSuccess 已记录。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **B06 · 缺陷（运行）** 重复项目 ID 返回可理解的冲突提示。当前：后端 raw 500，前端展示解析异常。证据：[D17](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d17)、[D18](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d18)。
- [ ] **B07 · 缺陷（运行）** 允许创建的项目 ID 必须能再次读取和删除。当前：bad/project 创建成功但路由读取删除 404。证据：[D17](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d17)。
- [ ] **B08 · 增强（代码）** 首次进入产品能获得 MCP 与首次下发引导。当前：当前主要依靠外部 README，建议补产品内引导。证据：[G09](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g09)。
- [ ] **B09 · 缺陷（浏览器）** 切换项目时选择器、指标和账本始终一致。当前：旧项目慢响应可以覆盖当前项目账本。证据：[D01](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d01)。
- [x] **B10 · 通过（浏览器）** 删除项目要求准确输入目标项目 ID。当前：错误输入禁用，正确输入启用，空项目删除成功。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **B11 · 缺陷（运行）** 含正常业务数据的项目可以按声明策略清理。当前：含规则或需求的项目删除触发外键错误。证据：[D03](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d03)。
- [ ] **B12 · 缺陷（浏览器）** 刷新后恢复用户当前项目和页面。当前：B 项目反馈页刷新回到 A 项目 Explorer。证据：[D28](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d28)。

<a id="group-c"></a>
## C. 任务与需求的领域流程

- [x] **C01 · 通过（测试）** 需求原文与后续完成摘要分别保存。当前：原文保留、归档快照相关测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **C02 · 通过（测试）** 相同请求身份重复提交不会产生重复需求。当前：版本与请求幂等相关用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **C03 · 通过（代码）** 归档必须提供有效完成摘要。当前：归档输入及领域校验存在。证据：[HTTP 入口](D:/1/github/codeneuro/src/codeneuro/adapters/http/api.py)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **C04 · 通过（测试）** 需求归档携带并核对预期版本。当前：过期版本不会静默覆盖新状态。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **C05 · 通过（测试/浏览器）** 最后一条活跃需求归档后 Task 同事务完成。当前：后端测试与浏览器归档均确认 archived。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **C06 · 通过（测试）** 归档一条需求停用其关联的活跃短期规则。当前：active 规则的正常路径已有测试。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [ ] **C07 · 缺陷（运行）** 归档后的需求不能通过遗留草稿重新施加规则。当前：多需求任务内的关联草稿可被激活并再次下发。证据：[D02](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d02)。
- [x] **C08 · 通过（测试）** 归档一条需求不误停其他活跃需求关联规则。当前：独立关联规则的测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **C09 · 通过（测试）** 暂停或已发布任务不能直接归档需求。当前：相关状态约束测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **C10 · 通过（测试）** 暂停后恢复可还原原 active/testing 状态。当前：resume 恢复 testing 的用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **C11 · 缺陷（代码）** 六态任务均有定义明确的公开进入和退出路径。当前：公开入口未覆盖完整 draft/testing/released 流程。证据：[D22](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d22)。
- [ ] **C12 · 缺陷（代码/契约）** 无需求任务有明确人工完成入口。当前：契约承诺存在，当前公开入口缺失。证据：[D22](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d22)。
- [x] **C13 · 通过（并发测试）** 同时归档最后一条需求不会重复完成任务。当前：并发归档测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **C14 · 通过（回滚测试）** 审计失败时需求、规则和任务状态一起回滚。当前：事务回滚测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **C15 · 通过（浏览器）** 人类能通过 Web 归档需求并提供摘要。当前：本轮正常归档流程成功。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **C16 · 增强（代码）** 人类提交前可主动决定复用哪个任务或新建。当前：目前任意 Task 选择和强制新建能力不足。证据：[G05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g05)。

<a id="group-d"></a>
## D. Session、Worktree 与多端协作

- [x] **D01 · 通过（测试）** 同一 Worktree 的身份不能被不同声明偷偷重绑。当前：工作区身份稳定性测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **D02 · 通过（测试）** 会话绑定项目和任务时执行作用域一致性校验。当前：跨项目或非适用任务受到限制。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[会话用例](D:/1/github/codeneuro/src/codeneuro/workflows/workspaces.py)。
- [x] **D03 · 通过（代码）** 只能为 active/testing Task 启动任务会话。当前：start_session 显式检查状态。证据：[会话用例](D:/1/github/codeneuro/src/codeneuro/workflows/workspaces.py)。
- [x] **D04 · 通过（代码/测试）** 文件参数按工作区相对路径语义校验。当前：领域路径校验和范围测试有覆盖。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[JIT 策略](D:/1/github/codeneuro/src/codeneuro/modules/context.py)。
- [ ] **D05 · 缺陷（运行）** 远程声明工作区不触发服务器同路径扫描。当前：tree API 直接访问 Hub 本地目录。证据：[D04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d04)。
- [ ] **D06 · 缺陷（代码）** 工作区视角由用户或会话明确选定。当前：设置与树 API 默认使用排序第一条。证据：[D29](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d29)。
- [x] **D07 · 通过（代码）** 关闭的 Session 不能继续当作活跃会话使用。当前：公共会话检查显式调用 require_active。证据：[会话用例](D:/1/github/codeneuro/src/codeneuro/workflows/workspaces.py)。
- [ ] **D08 · 增强（运行/代码）** 关闭会话的草稿可以通过显式治理流程交接。当前：新会话接手被禁止，目前无恢复入口。证据：[G04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g04)。
- [ ] **D09 · 缺陷（文档/运行）** 反馈需要的 Debug 会话前提清晰可见。当前：默认 debug=False，主流程说明遗漏该门槛。证据：[D21](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d21)。
- [x] **D10 · 通过（测试）** 同项目多 Worktree 共享长期契约但不串任务规则。当前：两个 Worktree 的隔离用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **D11 · 增强（代码）** 人类能查看所有会话、工作区和声明更新时间。当前：现有页面没有完整会话/工作区监测。证据：[G06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g06)。
- [ ] **D12 · 待验证（待验证）** 跨机器真实 MCP 客户端能完成相同业务流程。当前：尚未进行真实双机器部署及断连重接验收。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。

<a id="group-e"></a>
## E. JIT 上下文与规则适用性

- [x] **E01 · 通过（运行/代码）** 作用域匹配区分 pay 与 payment 等目录边界。当前：后端 anchored matching 与合成探针对照正确。证据：[专项后端](D:/1/github/codeneuro/docs/audit-2026-10-12/backend-results.json)。
- [x] **E02 · 通过（运行）** 递归通配符正确匹配嵌套文件。当前：后端 src/**/*.py 参考结果符合预期。证据：[专项后端](D:/1/github/codeneuro/docs/audit-2026-10-12/backend-results.json)。
- [x] **E03 · 通过（运行）** 单星号只按约定路径段匹配，不等价全局范围。当前：后端参考结果对嵌套文件为 false。证据：[专项后端](D:/1/github/codeneuro/docs/audit-2026-10-12/backend-results.json)。
- [x] **E04 · 通过（测试）** P0 不因预算不足被静默省略。当前：核心预算用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E05 · 通过（测试）** P0 不因类别筛选被静默省略。当前：类别/优先级组合测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E06 · 通过（测试）** 已知反馈不会使 P0 被简写或降级。当前：P0 保留与已知反馈相关用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E07 · 通过（代码/测试）** 多文件及意图使用同一上下文装配策略。当前：统一 ContextQuery 和装配路径存在。证据：[JIT 策略](D:/1/github/codeneuro/src/codeneuro/modules/context.py)、[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E08 · 通过（测试）** 实际下发记录绑定会话、规则/需求版本。当前：Delivery 版本与事务相关用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E09 · 通过（测试）** 预览不产生真实下发或评分资格。当前：真实交付资格相关测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E10 · 通过（测试）** 冲突提示仅引用本次仍存在且版本匹配的候选。当前：reported conflict 版本过滤用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E11 · 通过（代码/文档）** 未配置语义评估时不伪称模型诊断。当前：返回 not_assessed 的语义明确。证据：[架构说明](D:/1/github/codeneuro/docs/architecture.md)、[JIT 策略](D:/1/github/codeneuro/src/codeneuro/modules/context.py)。
- [x] **E12 · 通过（测试）** Finding 只在同一活跃任务内按路径提示。当前：同任务跨会话与跨任务边界测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E13 · 通过（测试）** 重复相同请求保持约定的下发幂等。当前：同 query 重试与 request_id 用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **E14 · 通过（并发测试）** 装配期间规则修订变化时重核后再签发。当前：新增 P0 后重校验用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [ ] **E15 · 缺陷（浏览器/对照）** Web 文件适用规则与真正 JIT 的语义相同。当前：前缀、通配符和任务视角均不一致。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **E16 · 增强（代码）** 人类能回看某次真实下发包含的版本和来源。当前：工作台缺少 Delivery 详情入口。证据：[G07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g07)。

<a id="group-f"></a>
## F. 规则治理、测试证据与晋升

- [x] **F01 · 通过（测试）** Agent 新建规则首先处于草稿且不进入 JIT。当前：草稿治理测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F02 · 通过（测试）** 激活至少需要两份不同的成功测试证据。当前：换 request_id 不能伪造独立报告的测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F03 · 通过（代码/测试）** 测试报告标明客户端上报而非 Hub 执行。当前：报告来源和 MCP 行为与契约一致。证据：[治理说明](D:/1/github/codeneuro/docs/governance.md)、[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F04 · 通过（测试）** 旧报告不能用于验证之后的新条款版本。当前：证据接收时间及版本相关测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F05 · 通过（测试）** 修改条款或提升优先级会重置必要证据。当前：回到草稿重新验证的用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F06 · 通过（代码）** 激活核对最低置信度及有效观察。当前：治理策略存在阈值与观察计算。证据：[治理说明](D:/1/github/codeneuro/docs/governance.md)。
- [x] **F07 · 通过（测试）** 失败报告不能作为支持证据，反证会影响激活。当前：Agent rule 治理测试包含相关限制。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[核心测试](D:/1/github/codeneuro/tests/test_product_core.py)。
- [x] **F08 · 通过（代码）** 普通会话不能直接更改其他会话的草稿。当前：原始 Session 归属检查存在。证据：[G04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g04)。
- [x] **F09 · 通过（测试）** 晋升核对当前任务、规则状态与预期版本。当前：promote_rule 约束测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F10 · 通过（测试）** 晋升原样保留条款范围优先级并保留来源版本。当前：晋升用例通过，来源退出活跃下发。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F11 · 通过（测试）** Agent 修改已有长期契约必须走人工审阅。当前：直接扩大长期规则权限被治理边界约束。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **F12 · 通过（测试/浏览器）** 审批时目标版本已变则拒绝自动套用。当前：真实 stale proposal 返回 409。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)、[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **F13 · 缺陷（运行）** 需求归档会阻止其草稿以后被激活。当前：关联需求状态没有在激活时重新检查。证据：[D02](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d02)。
- [ ] **F14 · 增强（代码）** 人类能检查某规则激活所依赖的完整证据。当前：ledger 和 UI 不展示报告/置信度链。证据：[G03](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g03)。

<a id="group-g"></a>
## G. 反馈、问题报告与审计闭环

- [x] **G01 · 通过（测试）** 评分必须针对本会话真实下发过的规则版本。当前：Feedback 资格检查相关测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **G02 · 通过（测试）** 未下发及仅预览不能获得评分资格。当前：MCP 与上下文行为测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **G03 · 通过（测试）** 效用均分排除 0=已知的反馈。当前：当前版本统计测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **G04 · 通过（测试）** 已知反馈仅作用于本会话相应版本。当前：已知反馈与版本隔离有测试。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **G05 · 缺陷（运行）** 界面区分下发次数和评价次数。当前：111 次实际下发只显示 1 次引用。证据：[D13](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d13)。
- [ ] **G06 · 缺陷（文档/运行）** 评分及 Issue 的 Debug 限制能从主流程获知。当前：接入文档未解释必要开关。证据：[D21](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d21)。
- [x] **G07 · 通过（测试）** Issue 相关规则与会话任务保持作用域一致。当前：Finding/Issue Debug 及任务边界用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **G08 · 增强（代码）** 已上报 Issue 能进入人工处理、结论与关闭流程。当前：当前只有保存与部分冲突提示，缺 Web 处理入口。证据：[G02](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g02)。
- [x] **G09 · 通过（测试）** 过期规则版本的冲突报告不会伪装当前结论。当前：reported conflict 用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **G10 · 通过（测试）** 关键变更及其审计记录同事务成功或失败。当前：归档审计回滚用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **G11 · 缺陷（运行）** 审计历史超过 100 条仍可查找。当前：API 静默限制最新 100 条，没有翻页。证据：[D20](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d20)。
- [ ] **G12 · 增强（代码）** 人类可以从反馈追溯 Delivery 和对应版本。当前：账本只提供汇总字段，缺详情链。证据：[G07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g07)。

<a id="group-h"></a>
## H. Explorer：规则作用域页面

- [ ] **H01 · 缺陷（运行）** 目录来源与选定工作区真实对应。当前：客户端声明路径被 Hub 扫描，来源不可靠。证据：[D04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d04)、[D29](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d29)。
- [ ] **H02 · 缺陷（代码/浏览器）** 项目规则概览与当前 Task 下发预览清楚区分。当前：不同任务规则混合展示且缺少明确任务预览上下文。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **H03 · 缺陷（运行）** 目录前缀相似时不会误显示规则。当前：pay 范围出现在 payment 文件上。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **H04 · 缺陷（运行）** 嵌套扩展名 glob 能正确显示匹配规则。当前：src/**/*.py 在页面匹配遗漏。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **H05 · 缺陷（代码/运行）** 单星号与双星号的全局/根路径语义正确。当前：页面把单星号作为全局继承。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **H06 · 缺陷（代码）** 节点优先级统计正确区分 P0/P1/P2。当前：非 P0 统一进入 P1 计数。证据：[D05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d05)。
- [ ] **H07 · 缺陷（浏览器）** 三层以下的目录可以展开和选择。当前：第三层无 expander，第四层不渲染。证据：[D15](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d15)。
- [ ] **H08 · 缺陷（浏览器）** 搜索嵌套文件会保留其祖先路径并显示结果。当前：搜索已存在 refund.py 返回零行。证据：[D16](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d16)。
- [x] **H09 · 通过（浏览器）** 可见节点点击后能切换选中路径。当前：专项浏览器实际选择并记录 charge.py。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **H10 · 部分（浏览器/代码）** 没有代码树时能解释原因并指导下一步。当前：存在空项目视图，但缺来源和索引引导。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)、[G09](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g09)。
- [ ] **H11 · 缺陷（浏览器）** 规则详情长内容和底部区域可滚动触达。当前：固定最低高度与外层裁切冲突。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)。
- [ ] **H12 · 缺陷（浏览器）** 树与右侧详情宽度分配不受外层侧栏样式污染。当前：内层 main 额外继承 240px 左边距。证据：[D11](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d11)。
- [ ] **H13 · 待验证（待验证）** 大目录展开、过滤和切换仍保持可接受响应。当前：本轮只使用小型合成树，未做规模性能测试。证据：[Explorer 实现](D:/1/github/codeneuro/web/src/components/views/ExplorerView.vue)。
- [ ] **H14 · 增强（代码）** 目录显示 Worktree、数据来源和采集时间。当前：当前缺少真实索引来源的完整标识。证据：[G06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g06)。

<a id="group-i"></a>
## I. Tasks：需求与任务页面

- [x] **I01 · 通过（浏览器）** 提交合法需求会创建或归入目标任务并更新账本。当前：本轮正常需求录入成功。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **I02 · 缺陷（故障注入）** 提交失败后保留原文和任务选择。当前：503 后输入变空。证据：[D09](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d09)。
- [x] **I03 · 通过（代码）** 多候选任务时要求明确选择后再提交。当前：界面存在候选 radio 和提交禁用条件。证据：[Tasks 实现](D:/1/github/codeneuro/web/src/components/views/TasksView.vue)。
- [ ] **I04 · 增强（代码）** 单候选或无候选时仍可主动选择其他任务/新建。当前：目前依赖完整标题子串匹配。证据：[G05](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g05)。
- [x] **I05 · 通过（代码）** 任务列表搜索覆盖标题和描述。当前：filteredTasks 同时检查两字段。证据：[Tasks 实现](D:/1/github/codeneuro/web/src/components/views/TasksView.vue)。
- [x] **I06 · 通过（代码）** 可在任务泳道与列表视图之间切换。当前：两种 viewMode 和对应模板存在。证据：[Tasks 实现](D:/1/github/codeneuro/web/src/components/views/TasksView.vue)。
- [x] **I07 · 通过（代码）** 任务进度按归档需求数计算且处理零需求。当前：零分母分支和已完成计数存在。证据：[Tasks 实现](D:/1/github/codeneuro/web/src/components/views/TasksView.vue)。
- [x] **I08 · 通过（浏览器）** 暂停活跃任务可提供理由并成功落库。当前：pause 专项流程成功。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **I09 · 通过（浏览器）** 恢复暂停任务可成功落库并刷新。当前：resume 专项流程成功。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **I10 · 通过（浏览器）** 归档需求后列表反映已完成状态。当前：archive 专项流程与后端状态已核对。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **I11 · 缺陷（浏览器）** 已打开的任务详情会跟随最新账本更新。当前：任务 archived 后抽屉仍显示 active。证据：[D19](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d19)。
- [ ] **I12 · 缺陷（代码）** 零需求任务也有可达的完成动作。当前：当前无公开完成入口。证据：[D22](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d22)。
- [ ] **I13 · 缺陷（代码）** 看板状态与真实可执行动作一致。当前：draft/testing/released 仅有部分模型和显示。证据：[D22](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d22)。
- [ ] **I14 · 缺陷（代码）** 任务卡片和详情的全部操作可用键盘到达。当前：点击容器及自定义抽屉缺少完整键盘契约。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **I15 · 部分（代码）** 提交过程中避免重复操作并保持重试身份。当前：busy 存在，完整重试幂等 UX 未建立。证据：[G10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g10)。
- [ ] **I16 · 部分（代码）** 空看板、无搜索结果、无需求任务有分别清楚的说明。当前：基础空态存在，下一步引导和完整状态验收不足。证据：[Tasks 实现](D:/1/github/codeneuro/web/src/components/views/TasksView.vue)、[G09](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g09)。

<a id="group-j"></a>
## J. Rules：项目规则库页面

- [x] **J01 · 通过（代码）** 默认可以只查看 active 规则。当前：状态筛选默认 active。证据：[Rules 实现](D:/1/github/codeneuro/web/src/components/views/RulesView.vue)。
- [x] **J02 · 通过（代码）** 规则列表具有文本检索入口。当前：search 与过滤逻辑存在。证据：[Rules 实现](D:/1/github/codeneuro/web/src/components/views/RulesView.vue)。
- [x] **J03 · 通过（代码）** 规则可按长期契约或任务短期规则筛选。当前：filterLifecycle 按 task_id 区分两类。证据：[Rules 实现](D:/1/github/codeneuro/web/src/components/views/RulesView.vue)。
- [ ] **J04 · 缺陷（代码/浏览器）** 所有生命周期状态都有准确的中文说明。当前：非 active 状态被过度简化。证据：[D14](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d14)。
- [ ] **J05 · 缺陷（浏览器）** 已停用筛选包含明确约定的 deprecated 规则。当前：当前仅返回 revoked。证据：[D14](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d14)。
- [ ] **J06 · 缺陷（浏览器）** 等待证据的草稿不会被标成已经停用。当前：draft 行显示停用。证据：[D14](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d14)。
- [x] **J07 · 通过（浏览器）** 选中规则能阅读具体条款。当前：稳定详情截图包含条款正文。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [x] **J08 · 通过（代码）** 规则详情呈现路径模式和长期/任务归属。当前：相关字段在模板内存在。证据：[Rules 实现](D:/1/github/codeneuro/web/src/components/views/RulesView.vue)。
- [ ] **J09 · 缺陷（运行）** 引用和评价指标有正确口径。当前：eval_count 被称作引用次数。证据：[D13](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d13)。
- [x] **J10 · 通过（代码）** 晋升规则可显示原始规则及版本来源字段。当前：origin_rule_id/origin_version 有基础呈现。证据：[Rules 实现](D:/1/github/codeneuro/web/src/components/views/RulesView.vue)。
- [ ] **J11 · 增强（代码）** 能逐版本查看规则历史和差异。当前：当前详情不是版本浏览器。证据：[G07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g07)。
- [ ] **J12 · 增强（代码）** 人类可从规则库创建初始契约并明确治理入口。当前：Web 无完整的初始契约创建流程。证据：[G01](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g01)。
- [ ] **J13 · 缺陷（浏览器）** 规则抽屉有稳定不透明背景及清楚边界。当前：缺失 token 导致 computed background 透明。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)。
- [ ] **J14 · 缺陷（浏览器/代码）** 规则行与抽屉支持 Enter、Escape、焦点恢复。当前：实测 Escape 不关闭且缺少完整 dialog 语义。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。

<a id="group-k"></a>
## K. Review：长期契约审阅页面

- [x] **K01 · 通过（浏览器）** 可以看到当前项目已有提案。当前：合成待审、已决议提案均已加载。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **K02 · 通过（代码/浏览器）** 提案明确显示目标规则及目标版本。当前：目标 ID 和版本字段在卡片内呈现。证据：[Review 实现](D:/1/github/codeneuro/web/src/components/views/ReviewView.vue)、[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **K03 · 通过（代码/浏览器）** 提案展示拟议条款、路径和变更依据。当前：这些字段在实际卡片中可见。证据：[Review 实现](D:/1/github/codeneuro/web/src/components/views/ReviewView.vue)、[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **K04 · 缺陷（浏览器）** 批准前能看见拟变更的优先级。当前：P1 改为 P2 的提案未展示 priority。证据：[D07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d07)。
- [ ] **K05 · 缺陷（浏览器）** 批准前能看见拟变更的类别。当前：category 不在预览内容内。证据：[D07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d07)。
- [ ] **K06 · 缺陷（代码）** 审阅能逐字段对照原版本与拟议版本。当前：当前仅呈现部分新值，没有完整前后差异。证据：[D07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d07)。
- [x] **K07 · 通过（浏览器/后端）** 合法批准请求能够应用目标版本变更。当前：本轮真实批准成功，显示错误另列。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [x] **K08 · 通过（浏览器）** 拒绝操作保存理由并显示拒绝状态。当前：rejection.tag 为已拒绝。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **K09 · 缺陷（浏览器）** 批准成功后显示已批准。当前：后端 approved 被映射为已拒绝。证据：[D06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d06)。
- [x] **K10 · 通过（浏览器）** 过期目标版本的批准操作被后端拒绝。当前：真实 stale review 返回冲突。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [x] **K11 · 通过（代码）** 决定提交前需要有效理由。当前：ReviewInput 和共享审批表单有理由字段约束。证据：[HTTP 入口](D:/1/github/codeneuro/src/codeneuro/adapters/http/api.py)、[Workbench 实现](D:/1/github/codeneuro/web/src/Workbench.vue)。
- [ ] **K12 · 缺陷（浏览器）** 所有提案及其按钮均可通过滚动到达。当前：长审阅列表在内容容器中被裁切。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)。
- [ ] **K13 · 增强（代码）** 待审和已决议提案可分别筛选便于处理。当前：页面直接遍历全部提案，建议增加状态视图。证据：[Review 实现](D:/1/github/codeneuro/web/src/components/views/ReviewView.vue)。
- [ ] **K14 · 部分（浏览器/代码）** 发生冲突后能明确刷新差异并重新审阅。当前：后端拒绝正确，但页面误报断连且恢复引导不足。证据：[D27](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d27)、[G10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g10)。

<a id="group-l"></a>
## L. Feedback：规则效用与开发便签页面

- [x] **L01 · 通过（代码/测试）** 效用均分沿用后端排除已知 0 分的结果。当前：avg_score 直接呈现，后端统计测试通过。证据：[Feedback 实现](D:/1/github/codeneuro/web/src/components/views/FeedbackView.vue)、[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **L02 · 通过（代码）** 无有效分数时显示缺失态而非伪造评分。当前：使用空值合并显示破折号。证据：[Feedback 实现](D:/1/github/codeneuro/web/src/components/views/FeedbackView.vue)。
- [x] **L03 · 通过（代码）** 反馈次数与已知次数分开且名称正确。当前：本页表头为反馈次数，并显示 known_count。证据：[Feedback 实现](D:/1/github/codeneuro/web/src/components/views/FeedbackView.vue)。
- [x] **L04 · 通过（代码）** Finding 展示文本、目标路径、任务来源及状态。当前：便签模板包括这些基础字段。证据：[Feedback 实现](D:/1/github/codeneuro/web/src/components/views/FeedbackView.vue)。
- [x] **L05 · 通过（代码）** 无规则与无 Finding 时分别显示空态。当前：两列均有相应空态分支。证据：[Feedback 实现](D:/1/github/codeneuro/web/src/components/views/FeedbackView.vue)。
- [ ] **L06 · 增强（代码）** 可以看到 Issue 并记录处理结论。当前：ledger 不包含 Issue，页面无处理入口。证据：[G02](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g02)。
- [ ] **L07 · 增强（代码）** 可从规则反馈进入相应下发/测试证据。当前：当前汇总数据缺少证据追溯入口。证据：[G03](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g03)、[G07](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g07)。
- [ ] **L08 · 增强（代码）** 页面宣称的工作区信息能够实际查看。当前：页面未渲染 Worktree 列表。证据：[G06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g06)。
- [ ] **L09 · 增强（代码）** 可查看会话状态和 Debug 反馈资格。当前：页面未渲染 Session 管理视图。证据：[G06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g06)。
- [ ] **L10 · 缺陷（静态/浏览器）** 两列卡片、文字和边框沿用有效的设计变量。当前：多处 --color-* 变量未定义。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)。

<a id="group-m"></a>
## M. Activity：变更审计页面

- [x] **M01 · 通过（代码）** 事件展示动作及发生时间。当前：action/created_at 字段有呈现。证据：[Activity 实现](D:/1/github/codeneuro/web/src/components/views/ActivityView.vue)。
- [x] **M02 · 通过（代码）** 无效时间能保留原值或明确缺失态。当前：formatTime 处理空值及无效日期。证据：[Activity 实现](D:/1/github/codeneuro/web/src/components/views/ActivityView.vue)。
- [x] **M03 · 通过（代码）** 事件显示目标实体和审计序列。当前：entity_id/sequence 在模板内存在。证据：[Activity 实现](D:/1/github/codeneuro/web/src/components/views/ActivityView.vue)。
- [ ] **M04 · 缺陷（运行）** 历史事件数量超过 100 条不会静默丢失可见性。当前：存储 163 条，API 只返回最新 100 条。证据：[D20](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d20)。
- [ ] **M05 · 缺陷（代码）** 可以翻页或用游标读取更早事件。当前：接口与页面均无该入口。证据：[D20](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d20)。
- [ ] **M06 · 缺陷（浏览器）** 当前已加载事件的末条可通过正常滚动到达。当前：页面长内容被外层 overflow hidden 截断。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)。
- [ ] **M07 · 增强（代码）** 能查看审计中的操作者标签及身份边界。当前：前端 AuditEvent 缺少 actor 呈现。证据：[G08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g08)。
- [ ] **M08 · 增强（代码）** 可以展开事件具体变更和业务理由。当前：页面未渲染 details。证据：[G08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g08)。
- [ ] **M09 · 增强（代码）** 按实体、动作和时间筛选事件。当前：当前时间线没有这些筛选。证据：[G08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g08)。
- [ ] **M10 · 增强（代码）** 事件可跳转到关联任务、需求、规则或提案。当前：目前主要显示裸实体 ID。证据：[G08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g08)。

<a id="group-n"></a>
## N. Settings：项目配置页面

- [x] **N01 · 通过（代码/浏览器）** 可查看和选择已注册项目。当前：项目选择与注册入口存在并能实际使用。证据：[Settings 实现](D:/1/github/codeneuro/web/src/components/views/ProjectSettingsView.vue)、[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [x] **N02 · 通过（浏览器）** 可通过注册弹窗建立合法项目。当前：专项浏览器创建成功。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **N03 · 缺陷（代码）** 工作区详情对应明确选中的 Worktree。当前：当前只取 worktrees[0]。证据：[D29](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d29)。
- [ ] **N04 · 部分（代码）** 本地路径、远程声明和服务器验证结果区分明确。当前：有客户端上报提示，但树接口又按本地目录读取。证据：[D04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d04)、[Settings 实现](D:/1/github/codeneuro/web/src/components/views/ProjectSettingsView.vue)。
- [x] **N05 · 通过（浏览器）** 危险操作必须输入准确项目 ID 才启用。当前：wrongDisabled/correctEnabled 均符合预期。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [x] **N06 · 通过（浏览器）** 删除空项目后项目列表与选中状态恢复正常。当前：本轮 deleteEmpty.deleted 为 true。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **N07 · 缺陷（运行/浏览器）** 删除含业务数据的项目按策略成功或明确阻止。当前：实际返回 raw 500 并被页面误解析。证据：[D03](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d03)、[D18](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d18)。
- [ ] **N08 · 缺陷（浏览器）** 危险区域在常见桌面高度下可到达。当前：删除按钮在视口以下且滚轮无法移动到。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)。
- [ ] **N09 · 缺陷（运行）** 设置流程不会注册不可被再次管理的 ID。当前：斜杠 ID 可创建但不可读删。证据：[D17](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d17)。
- [ ] **N10 · 缺陷（浏览器）** 配置页刷新仍处于相同项目与页签。当前：全局位置仅存在内存中。证据：[D28](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d28)。

<a id="group-o"></a>
## O. 导航、指标、消息与共享交互

- [x] **O01 · 通过（浏览器）** 7 个主导航入口可分别加载对应页面。当前：全部页面已在 4 种视口取证。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **O02 · 缺陷（浏览器）** 项目切换的异步响应不会串到当前页面。当前：乱序账本响应覆盖当前选择。证据：[D01](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d01)。
- [ ] **O03 · 部分（代码/浏览器）** 面包屑、标题、内容属于同一业务对象。当前：普通情况存在标题，乱序切换时关系不成立。证据：[D01](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d01)。
- [ ] **O04 · 部分（代码）** 加载中、提交中、失败和可重试状态清楚独立。当前：局部 busy 有实现，完整请求生命周期不足。证据：[G10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g10)。
- [ ] **O05 · 缺陷（浏览器）** 错误消息保留业务含义且不暴露 JSON 解析异常。当前：重复项目和非空删除显示 Unexpected token。证据：[D18](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d18)。
- [ ] **O06 · 缺陷（浏览器）** 连接健康状态与业务错误分开。当前：版本冲突触发服务连接异常提示。证据：[D27](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d27)。
- [ ] **O07 · 缺陷（浏览器）** 指标名称、解释和计算口径一致。当前：P0 指标统计所有活跃长期规则。证据：[D12](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d12)。
- [x] **O08 · 通过（代码）** 成功消息和错误提示具有可通知语义。当前：Workbench 使用 status/alert 等提示区域。证据：[Workbench 实现](D:/1/github/codeneuro/web/src/Workbench.vue)。
- [ ] **O09 · 缺陷（浏览器）** 项目和页签可以刷新恢复或通过链接定位。当前：URL 不表达位置，刷新回默认值。证据：[D28](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d28)。
- [x] **O10 · 通过（代码）** 命令面板提供导航搜索和直接点击入口。当前：results 过滤及 choose 处理存在。证据：[命令面板](D:/1/github/codeneuro/web/src/components/common/CommandPalette.vue)。
- [ ] **O11 · 缺陷（代码）** 命令面板方向键与 Enter 作用于当前选择。当前：Enter 总是第一项，缺少方向键处理。证据：[D23](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d23)。
- [ ] **O12 · 缺陷（DOM）** 确认表单有可访问名称并关联标题。当前：ActionDialog 没有 aria-label/labelledby。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。

<a id="group-p"></a>
## P. 布局、视觉层级与样式细节

- [ ] **P01 · 部分（视觉/代码）** 全部页面沿用一致的深色工作台设计体系。当前：基础方向一致，变量和共享样式缺失影响落实。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)。
- [ ] **P02 · 缺陷（静态）** 所有 CSS 自定义属性引用都能解析。当前：17 个未定义变量，共 44 处引用。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)、[样式检查](D:/1/github/codeneuro/docs/audit-2026-10-12/static-results.json)。
- [ ] **P03 · 缺陷（静态）** 公共标题、网格、面板、卡片类有实际样式。当前：section-head/grid/panel/card 等共享类缺失。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)。
- [ ] **P04 · 缺陷（几何测量）** 工作台外壳样式不影响内部 main 布局。当前：Explorer main 也继承 240px 左边距。证据：[D11](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d11)。
- [ ] **P05 · 缺陷（几何测量）** 跳转链接不会常态挤占主布局宽度。当前：skip-link 作为 flex 子元素占 84.25px。证据：[D11](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d11)。
- [ ] **P06 · 缺陷（浏览器）** 长页面有清楚一致的滚动责任。当前：Review/Activity/Settings 等存在不可达底部。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)。
- [ ] **P07 · 缺陷（computed style）** 覆盖式详情具有不透明面板背景。当前：稳定规则抽屉背景为 rgba(0,0,0,0)。证据：[D10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d10)。
- [x] **P08 · 通过（稳定截图/测量）** 1440px 视口下稳定规则抽屉不超出右边界。当前：x=900，width=540，right=1440；排除动画中截图误判。证据：[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [ ] **P09 · 缺陷（浏览器视口）** 390px 宽度下仍有可用内容区域或明确支持限制。当前：当前 7 页内容高均为 0，没有适配布局。证据：[D25](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d25)。
- [ ] **P10 · 部分（浏览器视口）** 768px 布局维持可读且操作可达。当前：有内容，但固定导航和长页面裁切仍影响使用。证据：[D08](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d08)、[D25](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d25)。
- [ ] **P11 · 缺陷（计算/测量）** 小号正文与辅助信息达到可读对比度。当前：11px 弱化文字仅 3.297:1/3.607:1。证据：[D26](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d26)。
- [ ] **P12 · 待验证（待验证）** 超长中文、英文单词、路径和标题不会遮挡关键动作。当前：本轮未做完整极端文本矩阵。证据：[共享样式](D:/1/github/codeneuro/web/src/style.css)。
- [ ] **P13 · 待验证（待验证）** 所有 hover/focus/active/disabled 状态均可辨认。当前：未对全部控件完成状态截图矩阵。证据：[共享样式](D:/1/github/codeneuro/web/src/style.css)。
- [ ] **P14 · 增强（代码）** 动效遵循用户减少动态效果偏好。当前：有抽屉动效但未见媒体查询适配，建议补充。证据：[共享样式](D:/1/github/codeneuro/web/src/style.css)、[样式检查](D:/1/github/codeneuro/docs/audit-2026-10-12/static-results.json)。

<a id="group-q"></a>
## Q. 键盘与可访问性

- [ ] **Q01 · 缺陷（代码/布局）** 跳过导航链接可见时位置正确且不破坏布局。当前：当前缺少 skip-link 专用样式。证据：[D11](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d11)。
- [ ] **Q02 · 缺陷（DOM）** 确认操作对话框有明确可访问名称。当前：原生 dialog 未关联可访问标题。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **Q03 · 缺陷（代码）** 自定义详情抽屉打开后约束焦点在当前层。当前：现有自定义抽屉没有完整焦点管理。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **Q04 · 缺陷（浏览器）** Escape 可以关闭自定义规则详情。当前：实际 Escape 后仍打开。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **Q05 · 缺陷（代码）** 关闭抽屉后焦点回到原触发位置。当前：未实现明确的焦点保存与恢复。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **Q06 · 缺陷（代码）** 可点击任务卡片和规则行有等价键盘操作。当前：当前主要依赖非按钮容器点击。证据：[D24](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d24)。
- [ ] **Q07 · 缺陷（代码）** 命令面板支持上下移动和选中结果反馈。当前：缺少选中索引与方向键处理。证据：[D23](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d23)。
- [ ] **Q08 · 缺陷（计算）** 必要的小号文字满足普通文本对比标准。当前：部分 caption 不足 4.5:1。证据：[D26](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d26)。
- [ ] **Q09 · 待验证（待验证）** 屏幕阅读器可理解导航、列表、状态和表单错误。当前：未使用 NVDA/其他读屏软件实机验收。证据：[前端 DTO](D:/1/github/codeneuro/web/src/types/ledger.ts)。
- [ ] **Q10 · 待验证（待验证）** 200% 缩放及仅键盘操作仍能完成全部业务流程。当前：本轮未做完整缩放/全流程键盘组合。证据：[共享样式](D:/1/github/codeneuro/web/src/style.css)。

<a id="group-r"></a>
## R. API、数据一致性与异常处理

- [ ] **R01 · 部分（代码）** HTTP/MCP 仅适配参数，业务走统一用例。当前：多数入口符合，tree 直接在 HTTP 扫描文件系统。证据：[D04](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d04)、[HTTP 入口](D:/1/github/codeneuro/src/codeneuro/adapters/http/api.py)。
- [x] **R02 · 通过（代码/运行）** 领域冲突可映射为明确 HTTP 状态。当前：真实过期审批得到 409，ProductError 有映射。证据：[HTTP 入口](D:/1/github/codeneuro/src/codeneuro/adapters/http/api.py)、[浏览器补充](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-followup.json)。
- [x] **R03 · 通过（测试）** 常规写入的 request_id 与版本约束能阻止重复/过期操作。当前：现有幂等与版本测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **R04 · 通过（回滚测试）** 跨实体业务变更保持事务原子性。当前：归档及审计失败回滚用例通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **R05 · 通过（测试）** 标准业务入口维持 Project/Task/Worktree 隔离。当前：常规会话与下发作用域测试通过，导入另列。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **R06 · 缺陷（静态/浏览器）** 前端 DTO 状态能约束后端真实枚举。当前：宽泛 string 掩盖 approved/applied 等错误。证据：[D06](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d06)、[D14](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d14)。
- [ ] **R07 · 缺陷（API）** 项目标识格式与路由契约一致。当前：斜杠 ID 导致创建后无法访问。证据：[D17](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d17)。
- [ ] **R08 · 缺陷（浏览器）** 纯文本/HTML/空错误响应能得到可理解提示。当前：请求封装无条件先 response.json。证据：[D18](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d18)。
- [ ] **R09 · 缺陷（浏览器）** 并发请求完成顺序不改变当前页面归属。当前：慢请求覆盖当前账本。证据：[D01](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d01)。
- [ ] **R10 · 增强（代码）** 请求有超时、取消与按操作类型设计的重试。当前：当前 fetch 封装未形成这些完整策略。证据：[G10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g10)。
- [ ] **R11 · 缺陷（运行）** 导入保持规则/需求版本与主表一致。当前：导入后首个 Delivery 外键失败。证据：[D31](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d31)。
- [ ] **R12 · 缺陷（运行/代码）** 导入未知关联必须明确处理而不扩大作用域。当前：未知项目自动回退，未知 task 可改成 None。证据：[D32](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d32)。

<a id="group-s"></a>
## S. 工程测试、构建、备份与发布

- [x] **S01 · 通过（运行）** 现有 Python 测试套件在本轮基线通过。当前：49 passed，54.71 秒；不代表额外缺陷不存在。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **S02 · 通过（运行）** 前端类型检查与生产构建通过。当前：vue-tsc 和 vite build 完成。证据：[前端构建](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **S03 · 通过（SHA-256）** 提交的前端静态产物对应当前源码构建。当前：重建 JS/CSS 与提交资产字节一致。证据：[产物比对](D:/1/github/codeneuro/docs/audit-2026-10-12/static-results.json)。
- [x] **S04 · 通过（浏览器）** 仓库现有浏览器冒烟本轮运行及清理完成。当前：本轮零 JS 异常，清理成功。证据：[浏览器冒烟](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **S05 · 通过（代码）** CI 配置包含 Windows 与 Ubuntu 的 Python 测试任务。当前：已检查配置，不代表本轮远程 CI 已运行。证据：[CI 配置](D:/1/github/codeneuro/.github/workflows/cross-platform.yml)。
- [ ] **S06 · 增强（代码）** 前端构建和关键用户流程进入持续回归。当前：CI 主要运行 pytest，Web 仅 build 脚本。证据：[G11](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g11)、[CI 配置](D:/1/github/codeneuro/.github/workflows/cross-platform.yml)。
- [ ] **S07 · 缺陷（代码）** 架构测试覆盖绝对导入和相对导入。当前：AST 检查忽略 ImportFrom.level 非零。证据：[D30](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d30)。
- [x] **S08 · 通过（运行）** 合成 SQLite 数据可备份并重新打开验证。当前：副本 integrity ok，无外键违规。证据：[备份恢复](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [x] **S09 · 通过（测试）** 迁移在新库显式执行且拒绝隐式改写旧库。当前：legacy/unknown schema 拒绝写入测试通过。证据：[现有 pytest](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **S10 · 缺陷（运行）** 导入成功意味着版本链足以支持后续业务。当前：当前插入主表却无快照和审计。证据：[D31](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d31)。
- [ ] **S11 · 缺陷（运行/代码）** 导入的项目/任务映射准确且确定。当前：未知项目被放到集合首项，其他回退也不严谨。证据：[D32](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d32)。
- [x] **S12 · 通过（文件审查）** Python 与 Web 有依赖锁文件可用于复现。当前：requirements.lock 与 package-lock.json 存在。证据：[Python 依赖锁](D:/1/github/codeneuro/requirements.lock)、[Web 依赖锁](D:/1/github/codeneuro/web/package-lock.json)。
- [ ] **S13 · 待验证（待验证）** 从干净机器/环境安装 wheel 后可按文档启动。当前：当前环境缺 hatchling，未完成 clean install 演练。证据：[G12](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g12)。
- [ ] **S14 · 待验证（待验证）** 依赖漏洞、许可证与升级兼容性完成系统检查。当前：本轮未执行专门依赖安全或许可证审计。证据：[Python 依赖锁](D:/1/github/codeneuro/requirements.lock)、[Web 依赖锁](D:/1/github/codeneuro/web/package-lock.json)。

<a id="group-t"></a>
## T. 实机、规模及明确不纳入本期的范围

- [ ] **T01 · 待验证（待验证）** 真实跨机器 HTTP MCP 完成接入、断连、重连和业务闭环。当前：协议测试不能替代双机器实机。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。
- [ ] **T02 · 待验证（待验证）** Linux 本机部署与文件路径行为正确。当前：有 Ubuntu CI 配置，本轮执行环境仅 Windows。证据：[CI 配置](D:/1/github/codeneuro/.github/workflows/cross-platform.yml)。
- [ ] **T03 · 待验证（待验证）** Firefox/WebKit 等其他浏览器可执行关键页面流程。当前：本轮专项运行基于 Chrome。证据：[专项浏览器](D:/1/github/codeneuro/docs/audit-2026-10-12/browser-results.json)。
- [ ] **T04 · 待验证（待验证）** 实体平板/手机的触控、键盘和显示符合支持声明。当前：只有视口模拟，未使用实体移动设备。证据：[D25](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d25)。
- [ ] **T05 · 待验证（待验证）** 真实 Agent 长任务遵循主动上下文和归档流程。当前：本轮合成测试不证明真实多仓库长期效果。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。
- [ ] **T06 · 待验证（待验证）** 大项目、多会话并发下的延迟和资源占用满足目标。当前：未执行生产规模压力和稳定性测试。证据：[G10](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g10)。
- [ ] **T07 · 待验证（待验证）** 进程崩溃、断电、磁盘满时可按约定恢复。当前：事务单测不等同故障恢复演练。证据：[G12](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#g12)。
- [ ] **T08 · 待验证（待验证）** 生产备份能在新机器恢复并继续 MCP/Web 业务。当前：本轮只验证合成数据库副本。证据：[备份恢复](D:/1/github/codeneuro/docs/audit-2026-10-12/verification-summary.json)。
- [ ] **T09 · 待验证（待验证）** 真实历史资产有可审阅的映射与完整迁移验收。当前：未使用现有 dist_batches，且已发现导入缺陷。证据：[D31](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d31)、[D32](D:/1/github/codeneuro/docs/product-audit-2026-10-12.md#d32)。
- [ ] **T10 · 范围外（产品边界）** 必须接入真实外部 LLM 才算当前核心产品可用。当前：不作为当前 JIT 的强制依赖；可选智能能力单独验收。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。
- [ ] **T11 · 范围外（产品边界）** 恢复宿主品牌钩子或生成静态规则副本。当前：现行契约明确取消，不列为缺失功能。证据：[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。
- [ ] **T12 · 范围外（产品边界）** 提供公网 SaaS 登录、计费和多租户体系。当前：现行范围为可信本机/网络服务，未把这些列为本期目标。证据：[README](D:/1/github/codeneuro/README.md)、[现行契约](D:/1/github/codeneuro/docs/product-contract.md)。

## 后续复测记录方式

复测时保留上述基线结果，在对应项后追加修复提交、执行环境、输入条件、实际结果和证据链接。仅在验收条件满足后修改勾选状态；为范围外能力作新产品决策时，先写清需求再调整范围。

建议优先复测报告的 11 项 P1，然后走完整桌面用户旅程。已通过的后端测试无需为每个文案或样式修改反复扩大范围；当共享行为、数据写入或并发边界改变时，再运行相应回归。
