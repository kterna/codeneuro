# Agent integration: Windows workspaces and Linux hosts

The workspace client runs beside the repository. The Hub never resolves a Windows path on the NAS. Use a project-scoped client token in `CODENEURO_TOKEN`; `.codeneuro.json` contains only `hub_url`, `project_id`, `active_task` and `token_env`. Pin the trusted Hub separately through `CODENEURO_HUB_URL` as required by the client. Do not commit tokens.

All four hosts can use the same CodeNeuro stdio MCP sidecar. Pi uses the explicit extension relay below because Pi 0.80.3 does not advertise a native MCP configuration surface.

## Shared sidecar process

Windows PowerShell, using the Python executable where CodeNeuro is installed:

```powershell
C:\CodeNeuro\venv\Scripts\python.exe -m codeneuro.cli mcp --config C:\Work\repo\.codeneuro.json --workspace C:\Work\repo --debug
```

Linux:

```sh
/path/to/venv/bin/python -m codeneuro.cli mcp --config /work/repo/.codeneuro.json --workspace /work/repo --debug
```

The MCP client launches this process; these commands also describe the exact command/args to put in each host. Debug mode exposes real receipt-backed scoring and issue tools. Sidecar read/edit/test tools inject context, run preflight and record actual results. Host-native hooks below add coverage for built-in tools. Scope-sensitive opaque shell scripts must use the sidecar command tool with explicit affected paths.

## Codex

Current verification target: `codex-cli 0.160.0`. `codex features list` reports `hooks stable true`. The actual CLI has `codex mcp add`, `codex app-server ...`, and **no `codex hooks` subcommand**.

Register the MCP process using the verified command syntax, substituting the local Python/workspace paths:

```sh
codex mcp add codeneuro -- /path/to/venv/bin/python -m codeneuro.cli mcp --config /work/repo/.codeneuro.json --workspace /work/repo --debug
```

This registration command updates the user's Codex configuration when the user chooses to run it; it was not run against the real user configuration during development. For manual setup, copy only the corresponding `mcp_servers.codeneuro` stanza into the intended trusted project/user config and preserve existing entries.

Generate the native project hook JSON for review:

```sh
/path/to/venv/bin/python -m codeneuro.integrations.codex_hooks --workspace /work/repo --print-config
```

The output is a `.codex/hooks.json` document containing PreToolUse, PostToolUse and SessionEnd command hooks. On Windows, use the installed venv's `python.exe`; generation uses Windows command-line quoting. Merge it into an existing hooks file after inspecting conflicts. The generator only prints JSON. It neither writes configuration nor marks hooks trusted.

Use Codex's native hook trust review to accept the specific generated commands. Changes to command/config produce a different trust hash and need review again. No `--dangerously-bypass-hook-trust` flag is required or recommended. Do not disable the Codex sandbox. A hook's `permissionDecision: deny` is a block; this adapter never returns permission approval.

Native behavior:

- Actual `exec_command` shell use arrives as hook `tool_name: "Bash"`, with `tool_input.command`. Concrete reads such as `cat`, `Get-Content`, and file-targeted `sed` fetch scoped context and inject the Hub delivery receipt through `hookSpecificOutput.additionalContext`.
- Declared file edits or patch payloads fetch context and obtain a semantic preflight receipt. Block/review results prevent the operation. Shell scripts whose file effects cannot be determined are blocked with explicit sidecar guidance; they are not silently marked covered.
- Operations bracket PreToolUse through PostToolUse with a Hub operation receipt, so task rebinding cannot cross the check/write boundary.
- In this installed version, PostToolUse's `tool_response` is a plain output string and omits exit status. The adapter submits test results only if the matching host-authored rollout `item_completed` record includes the exact tool ID, session, turn, command argv, timestamps and integer exit code. Missing terminal evidence is reported as missing. The sidecar test command is the reliable path when a host buffers or omits that record.
- SessionEnd performs idempotent cleanup. Local `.codeneuro/native-hooks.sqlite3` stores only operation IDs, accessed paths and event timing; no credentials or full transcripts are copied.

Host protocols can change across releases. Re-run the schema/runtime probe when upgrading Codex; the fixture schemas are explicitly pinned to 0.160.0.

## Claude Code

Verified installed version: `2.1.220`; `claude mcp add --help` lists stdio, project scope and command arguments after `--`.

```sh
claude mcp add --scope project --transport stdio codeneuro -- /path/to/venv/bin/python -m codeneuro.cli mcp --config /work/repo/.codeneuro.json --workspace /work/repo --debug
```

Use the Windows `python.exe` and Windows paths in PowerShell. Let Claude Code perform its normal project/server trust checks. These instructions establish standard MCP use; no unverified Claude native hook adapter is claimed. For automatic scope enforcement, use the CodeNeuro read/edit/test tools returned by the sidecar.

## Hermes

The installed Hermes CLI source (`hermes_cli/mcp_config.py`) supports stdio entries under `mcp_servers` with `command`, `args` and optional `env`. A reviewed configuration entry is:

```yaml
mcp_servers:
  codeneuro:
    command: /path/to/venv/bin/python
    args:
      - -m
      - codeneuro.cli
      - mcp
      - --config
      - /work/repo/.codeneuro.json
      - --workspace
      - /work/repo
      - --debug
```

The process environment must supply the trusted Hub and client token. Use literal Windows executable/config/workspace paths on a Windows Hermes installation. Preserve other MCP entries. Hermes's standard MCP loader owns startup; use the sidecar's governed tools for read/edit/test. This document does not claim that arbitrary Hermes built-in shell commands are intercepted by an uninstalled native hook.

## Pi: actual MCP relay and native extension

Verified installed version: `0.80.3`. Its local `docs/extensions.md` and declarations confirm `tool_call`, `tool_result`, `session_start`, `session_shutdown`, dynamic `registerTool()` and `ctx.sessionManager.getSessionId()`. The extension uses those interfaces. It does not invent a Pi `mcpServers` file.

Set `CODENEURO_PYTHON` to the Python executable that has CodeNeuro and MCP installed. Locate the shipped extension:

```sh
/path/to/venv/bin/python -c "from pathlib import Path; import codeneuro; print(Path(codeneuro.__file__).parent / 'integrations' / 'pi_extension.mjs')"
```

Start Pi from the intended workspace with an explicit, reviewed extension path:

```sh
pi -e /path/to/codeneuro/integrations/pi_extension.mjs
```

The extension launches `python -m codeneuro.integrations.pi_mcp`, which uses the real Python MCP SDK to initialize the stdio sidecar, list its tools and invoke them. MCP tools become Pi tools prefixed with `codeneuro_`; their actual JSON input schemas, results and errors are preserved. The same host session identity is shared with the native bridge, allowing its delivered rules to be rated through the sidecar.

For built-in read/edit/write/bash, the extension obtains native context/preflight before execution and appends rule context to the real tool result before the next model inference. Writes are blocked on preflight review/block. It never changes project trust or provider settings. Pi's `BashToolDetails` also lacks an exit code: native output is never converted into an invented test pass. Use the MCP test/command tool for recorded test execution.

## Evidence and limits of verification

Official OpenAI documentation/manual fetches were attempted first; this environment could not retrieve them (parent host requests returned HTTP 403; sandbox requests failed DNS). The Codex guidance above is therefore a disclosed local-version fallback, based on the actual 0.160.0 CLI, app-server `hooks/list`, and exact JSON wire schemas embedded in that executable. It is not attributed to an unread official page.

Development evidence:

1. Actual app-server `hooks/list` loaded project `.codex/hooks.json` with no parse errors, first as `untrusted`, then as `trusted` after the isolated test configuration recorded each reviewed current hash. Real user configuration was untouched.
2. An actual Codex CLI process, a disposable home/workspace and a local deterministic Responses protocol fixture executed `cat sample.txt`. Native PreToolUse and PostToolUse ran. Their additional context appeared as developer context in the next model request. This is a **host-protocol fixture**, not an external-model coding sample.
3. Captured native event fields were `session_id`, `turn_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `tool_name`, `tool_input`, `tool_use_id`; PostToolUse additionally contained `tool_response`. The shell command's authoritative terminal record contained command argv and exit code separately.
4. `tests/fixtures/codex-0.160/*.json` contains the extracted wire schemas. `tests/test_codex_hooks.py` validates output against them and checks real target resolution, denial, missing evidence, exact terminal records and Windows quoting.
5. `tests/test_pi_mcp.py` starts an independent real MCP fixture process and verifies initialize/list/call plus error propagation. Node checks the shipped extension's actual callback registration and recursion guard.
6. The shipped extension was loaded by the actual installed Pi 0.80.3 in offline RPC mode with an isolated Pi config. A fixture relay tool appeared in `pi.getAllTools()` as `codeneuro_probe_echo`, preserving its real JSON input schema; Pi `get_state` responded successfully and stderr was empty. This validates the actual extension loading/registration boundary separately from the real MCP wire test.

The native Codex runtime probe was performed on Linux. Windows quoting and path contracts are tested, but this is not evidence of execution on a real Windows Codex process. Actual long coding runs, external-model judgments, Windows host runtime and receipt-backed usefulness scores belong to the separate end-to-end acceptance record.
