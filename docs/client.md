# Native workspace client and stdio MCP

The workstation keeps its repository. CodeNeuro runs a local stdio MCP sidecar that reads native Windows or Linux paths, registers actual Git/machine identity, and contacts a pinned Hub through an independently issued project-scoped bearer token.

## Connection

Create a client credential from the Hub workbench's **工作区与会话 → 连接办公机 / Agent** flow. Save the returned token in the workstation's credential mechanism or process environment. The Hub returns that secret once. Do not put it in the repository.

The workspace `.codeneuro.json` contains nonsecret selection only:

```json
{
  "hub_url": "https://your-hub.example",
  "project_id": "your-project-id",
  "active_task": "your-task-id",
  "token_env": "CODENEURO_TOKEN"
}
```

On Linux, set the explicitly trusted destination and token in the environment used to launch the coding host:

```sh
export CODENEURO_HUB_URL='https://your-hub.example'
export CODENEURO_TOKEN='<the issued client token>'
python -m codeneuro.cli mcp --config '/actual/worktree/.codeneuro.json' --workspace '/actual/worktree' --debug
```

On Windows PowerShell:

```powershell
$env:CODENEURO_HUB_URL = 'https://your-hub.example'
$env:CODENEURO_TOKEN = '<the issued client token>'
python -m codeneuro.cli mcp --config 'C:\actual\worktree\.codeneuro.json' --workspace 'C:\actual\worktree' --debug
```

Install the same CodeNeuro package version as the Hub in the Python environment used by the host. Register that command and its arguments as the host's local stdio MCP service. Codex, Hermes and Claude Code have different configuration formats; use the verified host-specific integration documentation. Pi requires an MCP-capable adapter if its installation does not support MCP natively. The common service launch shape is `{command, args}`; credentials and the trusted Hub pin are inherited from the launch environment.

`discover_config()` walks from the requested directory to its ancestors. Discovery does **not** grant trust: `.codeneuro.json` can be changed by repository code, so `CODENEURO_HUB_URL` or the Python API's explicit `trusted_hub_url` must match before a bearer token or code metadata can leave the workstation. Redirects and inherited proxy environment settings are disabled. Only dedicated `CODENEURO_*TOKEN` environment variable names are accepted.

## File operations and provenance

`codeneuro_read_file` obtains scoped context automatically, then returns the real file text, SHA-256, line range and `delivery_id`. File tools reject path traversal, external absolute paths, credential locations, symlinks and Windows filesystem reparse points. The rule matcher receives canonical workspace-relative POSIX paths.

`codeneuro_edit_file` requires the SHA-256 returned by a read, the replacement text and a plan. New files use the explicit value `missing`; their parent directory must already exist. The client submits the **actual unified diff** to preflight and writes only when the Hub returns `decision=allow` without `stale`. `block`, `review`, missing decisions, hash conflicts and provider errors leave the file untouched. Accepted edits use an atomic replacement in the same directory and preserve an existing executable mode. POSIX directory descriptors protect file I/O from ancestor symlink replacement.

A Hub operation boundary brackets each sidecar read/edit/test. The Hub can therefore reject task rebinding while an operation is still using the pinned task. Interrupted operation records must be reconciled explicitly; an observation error does not prove a completed operation.

`codeneuro_index_workspace` builds bounded static metadata on the workstation with the common indexer. The indexer excludes credential locations, generated/vendor directories, symlinks and private-key markers. The client applies its credential-path filter again before transmitting the manifest. It does not ask the Linux Hub to read `C:\...` paths.

## Actual tests and Debug feedback

`codeneuro_run_tests` takes an argv list and affected paths. It uses `shell=False`, a workspace cwd, a deadline of at most 900 seconds, process-tree cleanup, a 10 MB output bound, and an environment without API-token/password/proxy variables. The returned exit code, timestamps and output come from the actual subprocess. Bounded redacted output is kept under `.codeneuro/test-runs/`; Hub excerpts are explicitly marked when truncated. An upload failure returns `recorded=false` and the local artifact path rather than pretending that the Hub accepted the evidence.

Tests execute trusted repository code with the current user's OS permissions. Workspace cwd and argv validation are **not an OS filesystem sandbox**. If a repository itself is untrusted, run the client in an appropriate OS/container sandbox before authorizing its tests.

Debug exposes both receipt-backed 0–5 rating and active issue reporting. The client never assigns ratings automatically. Scores must be supplied from actual observed usefulness. The browser acceptance fixtures and mocked-transport unit tests do not count as real coding-agent experiments.

## Native host hooks and session reuse

`create_native_bridge(config_path, workspace, host_session_id, agent_client)` supplies the verified host integration with context, preflight, real-test recording, operation boundaries and cleanup. Each hook process reuses the same Hub session keyed by trusted Hub, bearer identity, project, configured task, native workspace and actual host session ID.

State under `.codeneuro/native-sessions/` contains session IDs and up to 2000 receipt references, never bearer tokens or source content. POSIX `flock` and Windows `msvcrt` locks serialize restoration and atomic state updates. A restored session is checked with `session_status`. A network or server observation failure leaves the session identity intact and surfaces the error; it does not spawn a duplicate session. Cleanup retries with the same request ID return the stored result without opening another session.

Set `CODENEURO_HOST_SESSION_ID` and `CODENEURO_AGENT_CLIENT` for the MCP sidecar when the host adapter exposes those values. That sidecar and the native hooks then share receipt references, so a native file-access delivery can be rated through the MCP feedback tool. No global host configuration is modified by the client factory.

## Validation scope

`tests/test_client.py` checks trust pinning, redirect refusal, credential/path/symlink boundaries, actual local reads and atomic edits, SHA conflicts during assessment, block/review behavior, actual subprocess output/exit codes, child cleanup on timeout, session persistence, transient-status handling and MCP tool invocation. Its HTTP transport is an explicit deterministic test double. Integrated Hub tests and actual host-agent experiments provide separate evidence for network authorization and long coding runs.

Windows-specific locking, reparse-point and process-tree code is implemented using native platform branches. Linux execution alone does not establish that those branches have run on Windows; native Windows validation must be recorded separately.
