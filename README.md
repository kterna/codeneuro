# CodeNeuro

面向 Coding Agent 的任务、需求和规则上下文 Hub，提供 Web 工作台与 MCP 接口。

- 按项目和任务管理需求原文、完成摘要与任务状态。
- 按业务主题或文件范围检索规则，显式选择 P0–P3 优先级。
- 管理规则审阅、测试证据、下发记录与反馈。

## 安装与启动

需要 Python 3.11+。在仓库目录执行：

```sh
uv venv
uv pip install --python .venv/bin/python -r requirements.txt

# 初始化新数据库
.venv/bin/python -m codeneuro migrate --db /absolute/path/codeneuro.db

# 启动 Hub
.venv/bin/python -m codeneuro serve --db /absolute/path/codeneuro.db
```

Windows 将 `.venv/bin/python` 替换为 `.venv/Scripts/python.exe`。

打开 [http://127.0.0.1:8801/app/](http://127.0.0.1:8801/app/)，注册项目后即可使用工作台。已有数据库升级前须备份，参见[升级说明](docs/topics-v2.md)。

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

Hub 的 Streamable HTTP MCP 地址为 `http://127.0.0.1:8801/mcp/`。详细配置见 [MCP 接入指南](docs/agent-integrations.md)。

## 使用边界

- **Web API 和 MCP 无鉴权**，默认仅监听本机，不应直接暴露公网。
- Agent 主动查询上下文；Hub 不拦截文件操作，也不替 Agent 执行编码或测试。
- 规则以 Hub 数据库为准，不向工作区生成规则文件副本。

## 文档

- [客户端使用](docs/client.md)
- [主题与规则查询](docs/topics-v2.md)
- [规则治理](docs/governance.md)
