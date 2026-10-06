# 🧠 CodeNeuro (代码神经元中枢)

> **AI 编程时代的协同认知中枢**：为自主 Coding Agent（Cursor、Claude Code、Hermes、Windsurf 等）提供多项目/多 Worktree 统一管理、作用域规则热力图、长短期双轨记忆分层，以及运行时 Agent 自治治理的端到端基础设施。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Ready](https://img.shields.io/badge/MCP-Standard%20Ready-green.svg)](https://modelcontextprotocol.io)

---

## 🌟 为什么需要 CodeNeuro？

在日常深度使用 AI Coding Agent 时，开发者通常面临四个致命痛点：

1. **多工作区与 Git Worktree 隔离裂痕**：同时并行多个需求或多个 worktree 时，临时经验和规则分散在各处，分支切换或重新拉取目录后认知全部丢失。
2. **上下文污染与认知混淆**：把几百行架构规则和临时的需求重点混在一起丢给 Agent，导致 Prompt 膨胀、指令被稀释，严重时产生违背红线的幻觉。
3. **几十轮长程 Agent Loop 的重蹈覆辙**：Agent 在第 5 轮跑测试踩了坑，到了第 20 轮因为上下文滚动压缩而遗忘，重新踩同一个坑；或者前面的假设被推翻了，过时的短期规则没有及时撤销。
4. **不可见的黑盒状态**：缺乏全景看板，开发者无法直观审视整个代码库的规则复杂度、各目录的约束密度和优先级分布。

---

## 🏛️ 核心产品意识形态

```
                       ┌──────────────────────────────────────────────┐
                       │          产品需求 / PRD 输入 (WebUI)          │
                       └──────────────────────┬───────────────────────┘
                                              ▼
                    ┌───────────────────────────────────────────────────┐
                    │      Cognitive Ingestion Engine (认知拆解引擎)     │
                    │   - 影响面分析   - 优先级评级   - 规则与约束提炼   │
                    └─────────────────────────┬─────────────────────────┘
                                              │
                    ┌─────────────────────────▼─────────────────────────┐
                    │               中心化认知存储 (Central Hub)        │
                    │   [长期架构契约 (骨骼)]  +  [短期迭代记忆 (血液)] │
                    └───────────┬───────────────────────────┬───────────┘
                                │                           │
                 ┌──────────────▼──────────────┐            │
                 │   WebUI 认知全景看板        │            │  MCP 协议
                 │  - 目录树热力矩阵 / 优先级   │            │  (JIT 动态下发)
                 │  - 需求生命周期 / 记忆提炼  │            │
                 └─────────────────────────────┘            ▼
                                            ┌───────────────────────────┐
                                            │   各机器 / 并行 Worktrees  │
                                            │  (Cursor / Claude / ...)  │
                                            └───────────────────────────┘
```

### 1. 认知二元论：骨骼与血液 (Skeleton vs. Bloodstream)
- **长期架构记忆（骨骼 / Persistent）**：模块的架构契约（职责定位、对外承诺、接口协议、不可触碰的 P0 红线）。不随需求结束而改变。
- **短期需求记忆（血液 / Ephemeral）**：当前迭代（Task）特异性的改动重点、临时灰度逻辑、自测注意点。随需求交付自动归档或**升华结晶**。

### 2. JIT 局部视口探针 (Just-In-Time Scoped Context)
- **不触碰不加载，触碰即透视**：Agent 在接触特定文件（例如 `src/services/pay/calc.ts`）时，系统才通过纳秒级 Glob 匹配，动态合成：
  $$\text{Context} = \text{长期契约} + \text{当前任务重点(P0>P1>P2)} + \text{最新排坑经验}$$

### 3. Agent 循环自治与护栏 (Autonomous Self-Governance)
- **踩坑沉淀**：单测报错排查后，Agent 自动调用工具沉淀经验，避免后轮重犯。
- **动态修正**：假设推翻时，Agent 自主废弃失效短期规则。
- **架构护栏**：Agent 无权删除 P0 长期契约，只能提交变更提案（Proposal）由人类审批。

---

## 🚀 快速上手

### 1. 安装与启动

```bash
# 克隆仓库
git clone https://github.com/kterna/codeneuro.git
cd codeneuro

# 安装依赖 (推荐 uv)
uv venv
uv pip install -e .

# 启动 WebUI 与 REST API
python3 -m codeneuro.cli serve --port 8800
```

打开浏览器访问 `http://localhost:8800`，即可进入 **CodeNeuro 认知控制台**：
- 浏览目录树认知热力矩阵（P0/P1/P2 规则分布）
- 输入需求文本进行自动逆向拆解
- 审批 Agent 提交的架构提案与排坑发现
- 使用 JIT 上下文探针实时预览 Agent 接收到的提示词视图

### 2. 配置 MCP 接入 Coding Agent

在 Cursor、Claude Code 或 Windsurf 的 MCP 配置文件中添加：

```json
{
  "mcpServers": {
    "codeneuro": {
      "command": "python3",
      "args": ["-m", "codeneuro.cli", "mcp", "--db", "/绝对路径/codeneuro.db"]
    }
  }
}
```

---

## 🛠️ MCP 工具矩阵 (Agent Handheld Tools)

CodeNeuro 为 Coding Agent 提供了精简而强大的原子工具：

| 工具名 | 触发时机 | 功能与价值 |
| :--- | :--- | :--- |
| `codeneuro_get_context` | 读写或分析文件前 | 获取该文件精准匹配的长期契约与当前任务 P0/P1 约束 |
| `codeneuro_record_finding` | 测试报错自愈、排坑成功后 | 沉淀运行时避坑指南，避免后置轮次重踩同一个坑 |
| `codeneuro_patch_rule` | 重构方案变更、旧假设推翻时 | 自主废弃（revoke）或降级过时的短期规则，防止认知污染 |
| `codeneuro_propose_contract` | 发现长期架构契约需要变更时 | 向人类提交架构契约变更提案，防止 Agent 越权修改底线 |
| `codeneuro_list_active_rules` | 任务启动或审查时 | 查看当前项目与任务生效的完整规则清单 |

---

## 📂 项目结构

```text
codeneuro/
├── src/codeneuro/
│   ├── models.py        # 核心实体模型 (Project, Task, Rule, Finding, Proposal)
│   ├── storage.py       # SQLite (WAL) 高并发存储层
│   ├── matcher.py       # 纳秒级 Scope Matcher (Glob / 继承树)
│   ├── synthesizer.py   # Context 合成器 (优先级排序与 Prompt 渲染)
│   ├── decomposer.py    # 需求 PRD 自动拆解管道
│   ├── mcp_server.py    # FastMCP 标准协议服务端
│   ├── api.py           # FastAPI REST API 与静态路由
│   ├── static/          # 现代化响应式 WebUI 前端
│   └── cli.py           # CLI 命令行工具 (serve, mcp, sync)
├── tests/               # 完备的单元测试与端到端集成测试
└── pyproject.toml
```

---

## 📄 开源许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
