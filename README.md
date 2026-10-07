# CodeNeuro

为 coding agent 提供按项目、Git worktree、任务和文件范围隔离的规则上下文。包含 WebUI、HTTP API、stdio MCP、可追溯的下发与反馈，以及 SQLite 持久化。

当前实现面向**单机、受信任用户、多工作区**。工作区是服务所在机器上的真实目录。它不负责自动持续编程，也不把定时复测、页面预览或测试样例计作 Agent 使用成效。

## 安装和运行

已验证环境：Linux、Python 3.11、MCP Python SDK 2.3。依赖版本见 `requirements.lock`。

```sh
uv venv
uv pip install -r requirements.txt
.venv/bin/python -m codeneuro.cli serve --db ./codeneuro.db
```

默认地址 `http://127.0.0.1:8800`。需要局域网访问时显式指定 `--host 0.0.0.0`。可以通过 `CODENEURO_API_TOKEN` 保护 HTTP API；页面遇到 401 时会请求 Token，仅保存在当前页面内存。没有配置 Token 的实例仅适用于受信任网络。这不是多租户权限系统。

在页面中注册项目时填写真实仓库的绝对路径，然后创建任务和规则。普通长期规则不绑定任务；短期规则必须绑定任务。

## 接入 MCP

使用绝对数据库路径，确保 MCP 和 WebUI 指向同一份数据库。`--debug` 决定是否暴露评分及问题反馈工具。

```json
{
  "mcpServers": {
    "codeneuro": {
      "command": "/absolute/path/codeneuro/.venv/bin/python",
      "args": ["-m", "codeneuro.cli", "mcp", "--db", "/absolute/path/codeneuro/codeneuro.db", "--debug"]
    }
  }
}
```

Agent 使用顺序：

1. `codeneuro_list_projects` 获取项目；有需要时用 `codeneuro_create_task` 创建独立任务。
2. `codeneuro_start_session(project_id, workspace_path, task_id, agent_client)` 注册真实工作区，取得 `session_id`。
3. 访问文件前调用 `codeneuro_get_context(session_id, file_path, request_id)`。返回中包含规则 ID、版本和 `delivery_id`。同一次请求的重试使用相同 `request_id`，新的一次访问使用新 ID。
4. Debug 模式下用 `codeneuro_rate_rule(session_id, delivery_id, rule_id, score, reason)` 反馈真实下发。0 表示已经知道，1 表示无关，5 表示需要。
5. 用 `codeneuro_record_finding` 记录实际发现，用 `codeneuro_report_issue` 报告问题。短期规则可以按版本撤销；长期契约变更须提交 `codeneuro_propose_contract` 由人审核。
6. 完成会话调用 `codeneuro_end_session`。任务是否发布/归档由独立的任务生命周期决定。

**安装 MCP 并不会自动拦截文件读写。**需要将上述调用顺序放入 coding agent 的项目指令或工具调用集成。可使用 CLI 对接已有文件访问流程：

```sh
codeneuro session --db /path/state.db --project-id PROJECT --task-id TASK --workspace /path/worktree --debug
codeneuro context --db /path/state.db --session-id SESSION --file src/cache.py --request-id UNIQUE_REQUEST --json
codeneuro close-session --db /path/state.db --session-id SESSION
```

## 核心行为

- **工作区隔离**：会话固定项目、工作区、任务。共享 Git common dir 的真实 worktree 可以属于同一项目；不同任务的短期规则互不可见。
- **生命周期**：需求发布或归档，在同一事务中停用其活跃短期规则。重新打开任务不会偷偷恢复已停用规则。
- **版本一致性**：编辑、状态变更、回滚生成新快照；HTTP 写入需要 `expected_version`，冲突返回 409。
- **反馈语义**：评分必须引用本会话实际收到的规则及版本。相同下发/规则重复提交相同评分不重复计数。评分 0 只让原会话对原版本接收简短提醒；P0 始终完整保留，其他会话及新版本不受影响。
- **上下文预算**：按优先级控制正文大小，报告省略的非 P0 规则；P0 超出目标预算时显式报告，不能静默丢弃。
- **真实统计**：页面探针是只读预览。只有注册会话的实际下发生成凭据和命中计数；次数证明下发发生，不能证明模型遵从或代码质量改善。
- **需求录入**：页面提供离线关键词/显式路径候选提取，不调用 LLM、不自动激活。需要语义分析时，由 Agent 使用 `codeneuro_propose_rules` 提交结构化候选，人类核对范围后启用。
- **审计与恢复**：规则版本、任务状态、下发和反馈持久化；删除规则采用带版本记录的停用，保留历史证据。

## 静态规则导出

```sh
codeneuro export --db /path/state.db --project-id PROJECT --task-id TASK --out /path/worktree --format cursor
codeneuro export --db /path/state.db --project-id PROJECT --task-id TASK --out /path/worktree --format claude
```

导出使用同一生命周期过滤逻辑。Cursor 导出由 manifest 管理，只清理本工具生成的文件；CLAUDE.md 仅更新标记区，保留人工内容。文件原子替换，拒绝穿越工作区的符号链接。

静态文件是快照，规则变更或任务结束后应重新导出。旧版生成但没有 manifest 的规则不会被自动删除；升级前应单独备份、审阅这些旧文件，避免与新规则重复。

## 验证和维护

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q
codeneuro doctor --db ./codeneuro.db
python scripts/backup_db.py ./codeneuro.db ./backup.db
```

测试覆盖完整 HTTP 生命周期、真实 stdio JSON-RPC、多连接并发、事务失败回滚、路径边界、版本反馈、历史数据迁移和导出保护。`scripts/browser_smoke.py` 可用本机 Chromium 在临时数据库和独立浏览器配置中执行真实点击验收：

```sh
.venv/bin/python scripts/browser_smoke.py --chromium /path/to/chromium --screenshot /tmp/codeneuro.png
```

后台服务模板见 [deploy/codeneuro.service](deploy/codeneuro.service)。架构和升级说明见 [docs/architecture.md](docs/architecture.md) 与 [docs/upgrade-0.4.md](docs/upgrade-0.4.md)。
