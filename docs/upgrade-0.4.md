# 从 0.1/0.3 原型升级到 0.4

1. 停止旧的 WebUI 和 stdio MCP 进程；确认旧 runner / multirepo_worker 已退出。
2. 用 SQLite backup API 备份数据，保留旧源码提交和 Python 环境。
3. 在副本上启动新版本，检查迁移和 `codeneuro doctor`。
4. 更新源码/依赖并启动服务，检查 `/api/health`、项目和规则列表。
5. 让 MCP 客户端重新连接，读取新工具 schema。Agent 需要先 start_session，再按 session_id 请求上下文；Debug 评分需要实际 delivery_id。

## 保留的数据

项目、任务、规则和版本内容保留。已知的巡检假发现、示例评分/工单及模拟工作区被隔离，记录仍在数据库和备份中。旧的热力值保存于规则的 legacy_hit_count；新的 hit_count 只代表实际上下文下发。

## 协议变化

- GET `/api/context` 是只读预览。
- POST `/api/agent/sessions` 注册本机真实工作区。
- POST `/api/agent/context` 使用 session_id，返回 delivery_id 和实际下发内容。
- POST `/api/agent/feedback` 需要 session_id / delivery_id / rule_id / score。
- PUT 规则、PATCH 规则状态、回滚和停用需要 expected_version。409 应重新读取当前版本，不应自动重试覆盖。
- 需求提取生成 draft。审批通过前不会进入 Agent 上下文。
- 规则 DELETE 为保留历史的撤销。
- 默认关闭 debug 的 MCP 不暴露评分和问题反馈工具。

## 回滚

停止新 WebUI 及 MCP 进程，恢复旧源码与迁移前数据库后再启动旧版本。不要仅回滚代码让旧程序继续写新 schema。WAL 模式恢复时须确认所有数据库连接已关闭，移开旧的 `-wal` / `-shm` 文件后再恢复 SQLite 备份。

## 服务托管

可将 `deploy/codeneuro.service` 放入 `~/.config/systemd/user/`，按实际路径修改后执行：

```sh
systemctl --user daemon-reload
systemctl --user enable --now codeneuro.service
systemctl --user status codeneuro.service
```

默认仅监听 loopback。局域网部署在服务环境文件中设置 `CODENEURO_HOST=0.0.0.0`，并按网络信任边界配置 `CODENEURO_API_TOKEN`。令牌文件权限应为 600。
