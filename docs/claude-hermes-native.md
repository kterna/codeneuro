# Native Claude Code and Hermes tool coverage

The adapters here complement the shared stdio MCP sidecar. They add automatic scope retrieval for supported built-in file tools, use the same trusted Hub/client session, check modifications before execution, and close operation receipts after the host reports a terminal tool boundary. They never approve host permissions, disable a sandbox or infer successful tests from text output.

## Claude Code 2.1.220

The installed CLI and its shipped `sdk-tools.d.ts` were inspected. The actual CLI was then run with an isolated `CLAUDE_CONFIG_DIR`, an explicit disposable settings file, one allowed read-only tool, and a local deterministic Anthropic protocol fixture. Native `PreToolUse:Read` and `PostToolUse:Read` both executed. The additional context was present in the following model request. No real credentials or external model calls were involved.

Generate the settings fragment for review using the Python installation that contains CodeNeuro:

```powershell
C:\CodeNeuro\venv\Scripts\python.exe -m codeneuro.integrations.claude_hooks --workspace C:\Work\repo --print-config
```

```sh
/path/to/venv/bin/python -m codeneuro.integrations.claude_hooks --workspace /work/repo --print-config
```

The command only prints JSON. Merge its `hooks` entries into the intended project's `.claude/settings.json`, preserving existing entries, or load the reviewed fragment for an isolated run with `claude --settings /path/to/fragment.json`. The fragment registers:

| Event | Matched tools | Behavior |
|---|---|---|
| PreToolUse | Read, Edit, Write, Bash | Pin an operation, retrieve scoped context and receipt, check proposed edits, deny block/review results |
| PostToolUse | Same | Close the actual operation boundary |
| PostToolUseFailure | Same | Release the failed operation without reporting a pass |
| SessionEnd | Session | Idempotent session cleanup |

Concrete shell reads are resolved conservatively. Opaque shell scripts must use the CodeNeuro command tool with explicit paths. The adapter emits `permissionDecision: deny` when it cannot establish scope or preflight; it never returns permission approval. Keep normal Claude Code project/permission review enabled. The installed `--bare` and `--safe-mode` explicitly skip hooks, so they are unsuitable when testing native coverage.

The shipped Bash output type contains stdout, stderr, interruption/background flags and other metadata, but no integer process exit code. The adapter therefore does not reinterpret Claude transcripts as Codex rollout records or treat empty stderr as success. Use the shared MCP command/test tool for measured test evidence. The read/edit native context workflow remains automatic.

## Hermes Agent 0.21.5: native directory plugin

Hermes's actual runtime has `pre_tool_call`, `post_tool_call` and `transform_tool_result`. The last event is essential: `post_tool_call` is an observer and its return value is discarded; `pre_llm_call` runs at turn setup and would miss internal file-tool iterations. The bundled plugin uses the real `transform_tool_result` event to append the fetched scope and receipt to the tool result before it reaches the next inference.

Plugin source is shipped at:

```text
codeneuro/integrations/hermes_plugin/plugin.yaml
codeneuro/integrations/hermes_plugin/__init__.py
```

Find the absolute directory without editing Hermes:

```sh
/path/to/venv/bin/python -c "from pathlib import Path; import codeneuro; print(Path(codeneuro.__file__).parent / 'integrations' / 'hermes_plugin')"
```

Review these two files. The plugin imports only Python's standard library into the Hermes process and launches the configured CodeNeuro Python executable with an argv array. It adds no dependency to Hermes's Python environment. The worker inherits the user-supplied project token and trusted Hub pin and sends only workspace paths, proposed changes or actual terminal evidence to the shared client. It neither reads provider credentials nor changes Hermes tools, approvals or model configuration.

Use an isolated Hermes profile for initial verification. Its user plugin directory is `<profile-home>/plugins`; copy the reviewed plugin directory there under `codeneuro_native` and enable that registry key. The installed plugin scanner and CLI source verify both this directory and `hermes plugins enable <name>`. A reviewed profile fragment is:

```yaml
plugins:
  enabled:
    - codeneuro_native
  # The adapter's subprocess timeout is 180 seconds. Hermes's default callback
  # deadline is 30 seconds, so set this explicitly when model preflight can be slow.
  hook_callback_timeout: 200
```

Preserve existing plugin entries. No profile/global configuration was modified during development.

The launching process must provide:

```text
CODENEURO_PYTHON=<absolute Python executable with CodeNeuro installed>
CODENEURO_WORKSPACE=<absolute local repository/worktree root>
CODENEURO_HUB_URL=<trusted Hub URL>
CODENEURO_TOKEN=<project-scoped token from the environment>
```

On Windows use native `python.exe` and Windows paths; on Linux use the local venv's Python and POSIX paths. `.codeneuro.json` is discovered under the configured workspace. Each running workspace has its own pinned project/task session. A terminal tool's actual `workdir` is resolved inside that workspace; outside paths are rejected.

The plugin intercepts `read_file`, `write_file`, `patch` and `terminal`:

- Pre-tool retrieves scope automatically. Write/patch sends the proposed change for preflight. A block/review prevents execution.
- Post-tool releases the operation receipt. A foreground terminal test with an actual integer `exit_code` and known paths is recorded with the logical argv, actual output and observed hook timestamps. Hermes exposes combined `output`; the adapter does not claim separate OS stdout/stderr timing measurements.
- Transform preserves the original JSON fields and adds `codeneuro_context`; plain-text results retain their original text plus a marked context section. Context is consumed once for that actual tool call ID.
- Missing/null exit codes create no test outcome. Native background/PTY operations and timeouts over 180 seconds are directed to the sidecar command tool, whose live process handle provides the required ownership.
- Only `on_session_finalize` and `on_session_reset` close the Hub session. Hermes's confusingly named `on_session_end` fires after each user-message turn, so it deliberately does not trigger cleanup here.

MCP-prefixed tools are not intercepted again; they already have their own context/preflight. Use the same `CODENEURO_HOST_SESSION_ID` when the host launcher starts the MCP sidecar so native delivery receipts remain ratable through its debug tools.

## Verification evidence and remaining gates

`tests/test_claude_hermes_hooks.py` covers native field translation, automatic context, operation completion/failure, edit blocking, actual nonzero-result translation, missing-exit behavior, workdir scope, plugin registration and failure closure.

Additional isolated host probes used the actual installed executables/source:

Source identity on 2026-10-07: Hermes release `0.21.5`, Git HEAD `f97608f178d1ffeca59860195ab7da295f7c8e5f`; `model_tools.py` SHA-256 `5d5a947d84f31f1ba4ef5267e28154b819e8f957a0b378739696f1ac305e1509`. Claude Code `2.1.220` shipped `sdk-tools.d.ts` SHA-256 `aa765ef4053d51d36c9f93b2717f8ae5810375075b6b38eb377f69378f6edb24`.

- Claude Code 2.1.220 executed its real Read tool and both native hooks. The next request contained the context marker and the actual file result. Settings parsing and protocol execution succeeded with no stderr output.
- Hermes 0.21.5's real `PluginManager._load_plugin` loaded the shipped directory plugin, and `model_tools.handle_function_call` ran the real `read_file`, `patch` and `terminal` paths. Read retained `1|value = 7` and appended the receipt. A blocked patch left the file unchanged. A real intentionally failing pytest command returned `exit_code: 1`, and the worker preserved that value and output in its evidence request. Finalize passed through the actual hook manager.

These are protocol/integration fixtures using deterministic bridge/model responses. Their purpose is to prove the native host boundaries. They are not long external-model coding samples, usefulness ratings or evidence that a model's semantic judgment was correct. Actual Hub runs and receipt-backed ratings belong to the overall acceptance record. Windows path/argv contracts are supported, but these host probes ran on Linux; Windows runtime coverage still needs an actual Windows host.
