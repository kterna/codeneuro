# CodeNeuro 文档

这里仅保留当前代码的说明；已被替代的设计、升级步骤、实验计划与旧验收产物从工作树移除，历史材料按需查 Git。

| 文档 | 内容 |
| --- | --- |
| [产品契约](product-contract.md) | 产品职责、业务约束与信任边界 |
| [需求与任务](requirement-task-hierarchy.md) | 父目标、独立子任务、验证/整体验收及本地数据处理 |
| [客户端使用](client.md) | MCP 接入、任务选择、上下文查询和协作流程 |
| [MCP 与 HTTP](mcp-resources.md) | 资源、参数、分页、回执与工具目录 |
| [主题与查询](topics.md) | 受控词表、适用性和分类覆盖 |
| [规则治理](governance.md) | 草稿、证据、审阅、晋升与反馈 |
| [架构](architecture.md) | 模块边界、事务、存储与运行方式 |

安装与启动命令见[项目 README](../README.md)。验证入口为 `pytest tests`、`npm --prefix web run build`，以及使用临时库和临时浏览器的 `python scripts/browser_smoke.py --chromium <浏览器可执行文件>`。代码和文档中的验证步骤不等于已经执行的结果。
