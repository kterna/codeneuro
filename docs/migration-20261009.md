# Migration to another workstation

The tested branches are published to the repositories below:

```text
https://github.com/kterna/codeneuro.git          feature/full-product
https://github.com/kterna/astrbot_plugin_mcqq.git empirical/mcqq-command-policy
https://github.com/kterna/astrbot_plugin_mcqq.git empirical/mcqq-runtime-health
https://github.com/kterna/queqiao_mcdr.git       empirical/queqiao-resilience
```

Clone the CodeNeuro branch and install it with Python 3.11 or newer:

```powershell
git clone --branch feature/full-product https://github.com/kterna/codeneuro.git codeneuro
cd codeneuro
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

The full integrated branch currently passes 175 tests. The MCQQ branches use
the repository's existing bootstrap convention. Checkout directory names containing
hyphens can break package collection; run their tests with importlib mode:

```powershell
C:\work\codeneuro\.venv\Scripts\python.exe -m pytest tests --confcutdir=tests --import-mode=importlib -q --tb=short
```

Job A is expected to pass 37 tests, Job B 43 tests after the lifecycle follow-up,
and QueQiao's latest branch 50 tests. These numbers are local acceptance
evidence and should be re-run on the destination workstation.

Create a workstation `.codeneuro.json` beside the real worktree. Do not commit
it. The token belongs in an environment variable, never in this file:

```json
{
  "hub_url": "https://<your-codeneuro-host>",
  "project_id": "<project-id>",
  "active_task": "<task-id>",
  "token_env": "CODENEURO_TOKEN"
}
```

For a local sidecar, use the venv Python executable and pass the config and
workspace explicitly:

```powershell
$env:CODENEURO_HUB_URL = "https://<your-codeneuro-host>"
$env:CODENEURO_TOKEN = "<client-token-from-admin-enrollment>"
.\.venv\Scripts\python.exe -m codeneuro.cli mcp `
  --config C:\work\repo\.codeneuro.json `
  --workspace C:\work\repo --debug
```

The same sidecar command can be registered in Codex, Hermes, Claude Code or pi.
Use the native hook generators documented in `docs/agent-integrations.md` when
the host supports them. A Hub administrator must issue a project-scoped client
credential first; no credential is included in this repository.

For static Cursor/Claude files, run a one-shot sync or keep the watcher running:

```powershell
.\.venv\Scripts\python.exe -m codeneuro.cli sync --config C:\work\repo\.codeneuro.json --workspace C:\work\repo
.\.venv\Scripts\python.exe -m codeneuro.cli sync --watch --config C:\work\repo\.codeneuro.json --workspace C:\work\repo --format both
```

The published branches intentionally exclude `.codeneuro/`, bearer tokens,
provider keys, private model transcripts and empirical SQLite databases.
