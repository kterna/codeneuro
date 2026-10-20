# CodeNeuro

面向 Coding Agent 的任务、需求和规则上下文 Hub，提供 Web 工作台与 MCP 接口。

- 按 Project → Requirement → Task 管理整体业务目标和可独立开发、验证的子任务。
- 按业务主题或文件范围检索规则，显式选择 P0–P3 优先级。
- 管理规则审阅、测试证据、下发记录与反馈。

## 安装与启动

需要 Python 3.11+。在仓库目录执行：

```sh
uv venv
uv pip install --python .venv/bin/python -r requirements.txt

# 初始化新数据库
.venv/bin/python -m codeneuro init-db --db /absolute/path/codeneuro.db

# 启动 Hub
.venv/bin/python -m codeneuro serve --db /absolute/path/codeneuro.db
```

Windows 将 `.venv/bin/python` 替换为 `.venv/Scripts/python.exe`。

打开 [http://127.0.0.1:8801/app/](http://127.0.0.1:8801/app/)，注册项目后即可使用工作台。所有子任务验证完成后，需求等待用户整体验收。Agent 直接传项目和任务，无需创建或关闭 Session。

代码只维护当前模型和接口。已有本地数据用[一次性迁移脚本](scripts/migrate_local_data.py)转入新库，原库保留；操作说明见[需求与任务设计](docs/requirement-task-hierarchy.md#本地数据处理)。

## MCP 接入

支持 stdio MCP 的客户端可配置：

```json
{
  "mcpServers": {
    "codeneuro": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "codeneuro", "mcp", "--db", "/absolute/path/codeneuro.db"]
    }
  }
}
```

Hub 的 Streamable HTTP MCP 地址为 `http://127.0.0.1:8801/mcp/`。详细使用见 [客户端接入与使用](docs/client.md)。

## 使用边界

- **Web API 和 MCP 无鉴权**，默认仅监听本机，不应直接暴露公网。
- Agent 主动查询上下文；Hub 不拦截文件操作，也不替 Agent 执行编码或测试。
- 规则以 Hub 数据库为准，不向工作区生成规则文件副本。

## 文档

- [文档目录](docs/README.md)
- [需求与任务](docs/requirement-task-hierarchy.md)
- [客户端使用](docs/client.md)
- [MCP 与 HTTP 接口](docs/mcp-resources.md)
- [主题与规则查询](docs/topics.md)
- [规则治理](docs/governance.md)
