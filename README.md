# CodeNeuro

CodeNeuro 是面向 Coding Agent 的任务、需求和规则上下文 Hub。Agent 自己编码和测试；CodeNeuro 管理 Requirement、Rule、按文件范围下发的 JIT 上下文、下发凭据与反馈。所有生效规则只来自 Hub 数据库，不生成工作区 `CLAUDE.md`、`.cursor/rules` 副本，也不安装宿主专用钩子。

## 运行前提

Python 3.11+；依赖见 `requirements.txt` 和 `requirements.lock`。Web 工作台源码位于 `web/`，锁定依赖见 `web/package-lock.json`。

```sh
uv venv
uv pip install --python .venv/bin/python -r requirements.txt
npm ci --prefix web && npm run build --prefix web
```

Windows 使用 `.venv/Scripts/python.exe`。**仅对新建的空数据库**显式初始化：

```sh
.venv/bin/python -m codeneuro migrate --db /absolute/path/new-codeneuro.db
```

运行时拒绝旧版/未知 schema，不自动改写旧库。旧数据文件保持原状；不得把迁移命令指向生产旧库。

## 身份与服务

服务从操作员控制的环境变量读取客户端定义；仓库配置和 MCP 参数不能自行取得项目权限。下面的密钥只用于解释格式，实际值须由凭据管理器提供，不要写进仓库：

```sh
export CODENEURO_CLIENTS='[{"token_env":"CODENEURO_HUMAN_TOKEN","actor_id":"human-owner","project_ids":["my-project"],"role":"human"},{"token_env":"CODENEURO_AGENT_TOKEN","actor_id":"coding-agent","project_ids":["my-project"],"role":"agent"}]'
export CODENEURO_HUMAN_TOKEN='<独立的强密钥，至少 24 字符>'
export CODENEURO_AGENT_TOKEN='<另一独立强密钥，至少 24 字符>'
.venv/bin/python -m codeneuro serve --db /absolute/path/new-codeneuro.db
```

默认仅监听 `127.0.0.1:8801`。Web：`/app/`；认证的 streamable HTTP MCP：`/mcp/`。跨机器客户端应经可信网络/HTTPS 接入 Hub，**不共享 SQLite WAL 文件**；远程工作区与仓库身份是客户端声明，Hub 不声称访问过远端源码。

支持 stdio MCP 的宿主可配置：

```json
{
  "mcpServers": {
    "codeneuro": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "codeneuro", "mcp", "--db", "/absolute/path/new-codeneuro.db"]
    }
  }
}
```

`CODENEURO_CLIENTS`、它引用的密钥和 `CODENEURO_TOKEN` 必须由宿主的安全进程环境提供；不要将真实 Token 提交到 MCP 配置文件。详见 [标准 MCP 接入](docs/agent-integrations.md)。

## Agent 工作流

1. `codeneuro_list_tasks` 返回状态、标题、描述；Agent 在本地用正则检索，明确选择已有 Task 或 `codeneuro_create_task`。多候选不由 Hub 擅自绑定。人类可在 Web 提交一句话原文并明确选择歧义 Task。
2. `codeneuro_start_session` 绑定项目、Task、Worktree 和认证 actor；`codeneuro_submit_requirement` 保存独立 Requirement 原文。
3. Agent 在相关文件工作前主动调用 `codeneuro_get_context`。多文件、类别、意图、优先级和清单模式受同一 JIT 策略控制；P0 不因预算或已知反馈静默丢失。标准 MCP **不自动拦截**宿主内置的文件读写。
4. `codeneuro_record_finding` 记录观察；真实下发后才能 `codeneuro_rate_rule`（`0=已知，1=无关，5=核心需要`）或 `codeneuro_report_issue`。均分排除 0；预览或未下发不产生评分资格。
5. Agent 可创建当前任务草稿 Rule、主动上报**由宿主实际执行**的测试事件、附加版本证据并在满足条件后激活；可按版本晋升活跃短期 Rule。CodeNeuro 不运行测试。修改既有长期契约须先提案，由人类身份审阅。
6. Agent 确认某条需求已完成后提供摘要并调用 `codeneuro_archive_requirement`；最后一条归档自动完成 Task，关联短期规则退出下发。`paused/released` Task 不接受归档，需先走相应状态流程。

Web 账本展示项目契约、作用域规则密度、活跃和历史需求、Worktree 声明与可追溯事件；密度依据**已存规则范围**，不伪装成扫描了远程代码树。

## 验证及边界

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q
npm run build --prefix web
```

测试使用显式迁移的临时数据库，覆盖版本/事务回滚、并发归档、MCP stdio/HTTP、HTTP 鉴权及工作台 API。`scripts/browser_smoke.py` 使用隔离 Chromium 配置进行真实页面验收；当前 Windows 环境中页面业务动作通过，但临时日志文件清理仍可能因文件占用而失败，不能把它列为全绿浏览器验收。

语义分析、索引和模型诊断不是当前运行时的暗中回退；没有配置的能力不会伪称为模型结论。旧版产品的全量数据库导入、多仓库真实 Agent 效果或跨机器实机验收也尚未由这些测试证明。架构和业务边界见 [产品契约](docs/product-contract.md) 与 [实现规范](docs/rebuild-plan.md)。
