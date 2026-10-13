# 2026-10-12 产品审查证据

对应 [完整审查报告](../product-audit-2026-10-12.md) 与 [256 项验收清单](../product-audit-checklist-2026-10-12.md)。基线提交：`c30cd63c20f74c0b52c76d510b24bac0e4cc51a2`。

全部数据为本轮审查生成的合成项目、任务、规则、报告与工作区。目录路径中的用户名和随机 ID 仅用于关联本机复现记录。没有复制生产数据库、真实仓库文件内容或现有 `dist_batches/` 数据。本证据包不包含数据库文件，也不修改产品代码。

## 结果文件

| 文件 | 内容 | 重点关联 |
| --- | --- | --- |
| [backend-results.json](backend-results.json) | 合成实体 ID、范围参考、归档草稿、Debug、会话交接、删除、项目 ID、Hub 路径、审计及数据库结果 | D02–D05、D12/D13、D17、D20/D21、G04 |
| [browser-results.json](browser-results.json) | 全 7 页几何测量、DOM、特殊流程、故障注入、响应乱序与窄屏数据 | D01、D05/D06、D08/D09、D14–D16、D19、D24/D25、D28 |
| [browser-followup.json](browser-followup.json) | 稳定抽屉、真实批准/拒绝/过期审批、删除确认及非空删除 | D03、D06/D07、D10/D11、D17/D18、D27 |
| [static-results.json](static-results.json) | 缺失 CSS token/共享类、对比度、媒体查询、弱类型、构建资源一致性 | D10、D25/D26、V03 |
| [import-results.json](import-results.json) | 隔离导入退出码、快照数量、错误项目归属、首次下发外键错误 | D31/D32 |
| [verification-summary.json](verification-summary.json) | 本轮 pytest、构建、冒烟、备份恢复的执行结果摘要及证据边界 | V01–V08；不是完整终端日志 |
| [checklist-status.json](checklist-status.json) | 256 个检查点的结构化状态、方法、结果和来源 | 与 Markdown 清单同一批生成 |
| [manifest.json](manifest.json) | 保存文件的 SHA-256、大小与生成基线 | 校验保存后的证据完整性；不是业务正确性证明 |
| [artifact-validation.json](artifact-validation.json) | 报告/清单编号、链接、来源行号、原始证据比对与源码未改检查 | 交付文档自身的一致性验证 |

### 阅读 JSON 时的注意事项

- 49 个现有测试通过，与专项探针发现错误可以同时成立：后者覆盖了前者未覆盖的行为。
- `database_integrity=ok` 只说明被检查数据库结构完整性。导入缺少业务版本快照仍可能在首次 Delivery 时失败。
- 浏览器的 `pageErrors=[]` 表示没有未捕获 JS 异常，不表示业务、标签或布局正确。
- `command_palette_arrows` 记录只有一次 ArrowDown，不能据此单独推断应选中第二项。D23 依据键盘处理源码缺失。
- 原始 `rule-drawer.png` 截在动画期间。持续样式结论只使用 `rule-drawer-stable.png` 和后续 computed style。未把动画中的临时位置当成持续横向裁切问题。
- 四种视口均由 Chrome 模拟，不代表实体手机/平板或其他浏览器已经验收。
- pytest、构建、仓库冒烟、备份恢复的完整终端日志没有被保存在该目录；verification-summary 明确标注为本轮执行记录，不构造不存在的原始日志。

## 全页面截图

| 页面 | 1440×900 | 1280×720 | 768×1024 | 390×844 |
| --- | --- | --- | --- | --- |
| Explorer | [桌面](screenshots/desktop-explorer.png) | [笔记本](screenshots/width-1280-explorer.png) | [中等宽度](screenshots/width-768-explorer.png) | [窄屏](screenshots/width-390-explorer.png) |
| Tasks | [桌面](screenshots/desktop-tasks.png) | [笔记本](screenshots/width-1280-tasks.png) | [中等宽度](screenshots/width-768-tasks.png) | [窄屏](screenshots/width-390-tasks.png) |
| Rules | [桌面](screenshots/desktop-rules.png) | [笔记本](screenshots/width-1280-rules.png) | [中等宽度](screenshots/width-768-rules.png) | [窄屏](screenshots/width-390-rules.png) |
| Review | [桌面](screenshots/desktop-review.png) | [笔记本](screenshots/width-1280-review.png) | [中等宽度](screenshots/width-768-review.png) | [窄屏](screenshots/width-390-review.png) |
| Feedback | [桌面](screenshots/desktop-feedback.png) | [笔记本](screenshots/width-1280-feedback.png) | [中等宽度](screenshots/width-768-feedback.png) | [窄屏](screenshots/width-390-feedback.png) |
| Activity | [桌面](screenshots/desktop-activity.png) | [笔记本](screenshots/width-1280-activity.png) | [中等宽度](screenshots/width-768-activity.png) | [窄屏](screenshots/width-390-activity.png) |
| Settings | [桌面](screenshots/desktop-settings.png) | [笔记本](screenshots/width-1280-settings.png) | [中等宽度](screenshots/width-768-settings.png) | [窄屏](screenshots/width-390-settings.png) |

## 特殊状态截图

| 场景 | 截图 | 解释 |
| --- | --- | --- |
| 项目响应乱序 | [project-response-race.png](screenshots/project-response-race.png) | A 选择器下出现 B 专属规则 |
| 审批成功却显示拒绝 | [approval-success-wrong-label.png](screenshots/approval-success-wrong-label.png) | 状态文字与后端实际 approved 不符 |
| 过期审批 | [stale-review-conflict.png](screenshots/stale-review-conflict.png) | 正确冲突被错误解释为断连 |
| 非空项目删除 | [delete-populated-error.png](screenshots/delete-populated-error.png) | 外键失败和前端 JSON 解析错误 |
| 重复项目 | [duplicate-project-error.png](screenshots/duplicate-project-error.png) | 重复键没有友好冲突反馈 |
| 初始空项目 | [empty-project.png](screenshots/empty-project.png) | 合成空项目状态 |
| 创建后空项目 | [empty-created-project.png](screenshots/empty-created-project.png) | 成功创建后的视图 |
| 嵌套文件搜索 | [explorer-nested-search.png](screenshots/explorer-nested-search.png) | 已有文件搜索不到 |
| 范围匹配 | [explorer-wrong-scopes.png](screenshots/explorer-wrong-scopes.png) | 展示规则与后端参考不一致 |
| 需求提交失败 | [intake-failure.png](screenshots/intake-failure.png) | 错误出现后输入已丢失 |
| 稳定规则抽屉 | [rule-drawer-stable.png](screenshots/rule-drawer-stable.png) | 用于判断最终背景及布局 |
| 抽屉动画中 | [rule-drawer.png](screenshots/rule-drawer.png) | 仅保留原始过程，不作为持续裁切证据 |
| 设置页滚轮后 | [settings-after-wheel.png](screenshots/settings-after-wheel.png) | 危险区仍在视口之外 |
| 任务归档后详情 | [task-archived-stale-drawer.png](screenshots/task-archived-stale-drawer.png) | 详情头部仍保留旧 active 状态 |

截图总数为 42：7 页×4 个视口的 28 张，加 14 张特殊状态。没有复制含动画误导缩略图的旧 contact sheet。

## 探针脚本及复现条件

| 文件 | 作用 |
| --- | --- |
| [backend_probe.py](repro/backend_probe.py) | 在新的独立运行目录初始化合成数据库和工作区，运行后端探针，输出合成实体 ID |
| [browser_audit.cjs](repro/browser_audit.cjs) | 使用前一步实体及专用服务地址检查页面、请求乱序、错误和视口 |
| [browser_followup.cjs](repro/browser_followup.cjs) | 对稳定抽屉、实际审批及删除等进行补充验证 |
| [static_audit.py](repro/static_audit.py) | 扫描变量与样式，计算对比度，比较重建静态资源 |
| [import_probe.py](repro/import_probe.py) | 单独构造微型批次和新库，复现导入缺版本及错误归属 |

这些是保留的本轮审查探针，不是承诺跨平台即开即用的正式测试套件。脚本中包含本机 Playwright 和 Chrome 位置，运行前需适配依赖路径；静态资源比对需要提前生成独立 verified-build。浏览器用例会提交、归档、批准和删除其合成对象，应指向专用合成库服务。

复现顺序：固定该 Git 提交的源码快照 → 选择新的空临时运行目录 → 执行后端探针创建合成库 → 仅以该库启动专用本机服务 → 执行浏览器及补充探针 → 单独执行合成导入探针 → 收集结果并停止专用服务。不要把探针数据库路径替换成真实现有库，也不要把浏览器 base URL 指向正在使用的产品实例。

原始隔离位置为 `<TEMP_DIR>/codeneuro-audit-a23987212a`，服务使用 `127.0.0.1:18973`。该位置属于临时复现环境，不作为长期证据依赖；报告所引用的 JSON 和截图均已复制至本目录。
