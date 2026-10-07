# Empirical coding acceptance catalog

This catalog defines future work and acceptance gates. It is not a report of completed coding runs. Root provisions isolated worktrees, an authenticated CodeNeuro Hub, real provider processes, and MCP sidecars before dispatch. No task below authorizes modifying the deployed AstrBot/MCDR services, production credentials, or their live configuration.

## Repository inspection evidence

Inspected 2026-10-07. Revalidate HEAD and relevant code before launching; later changes may already solve a proposed item.

| Repository | Inspected HEAD | Observed starting point |
|---|---|---|
| `projects/astrbot_plugin_mcqq` | `0b69c51` | `RconSecurityGuard` is defined/tested and exported by `core/adapters/__init__.py`; `RconManager.execute_command()` does not invoke it. `PlayerListCache`, `WebSocketWatchdog`, `AlertDispatcher`, `WhitelistManager`, and `BatchCommandExecutor` are defined/tested but were not found in production callers. The actual player-list path is `CommandHandler.handle_player_list_command()` → `_request_api()` with correlated WebSocket waiters. |
| `projects/queqiao_mcdr` | `88ff7ae23426071b07c9651a65d86297795c97f4` | `ReconnectBackoff` and `McdrCommandGuard` are standalone helpers/tests. `WebSocketClient.start()` uses a linear retry delay and `asyncio.sleep`; `stop()` clears flags/closes a socket but does not itself wake that sleep. `ApiHandler` exposes broadcast/private/title/actionbar/player queries, **not arbitrary remote command execution**. Its title/actionbar methods generate commands for `server.execute()`. |
| `codeneuro` integration worktree | Record root's actual integrated HEAD at dispatch | Core receipt/version/lifecycle tests exist; the full-product work adds remote clients and governance/intelligence. There is no existing validated experiment evidence bundle export in the inspected baseline. Confirm the integration branch before starting Job D to avoid duplicating a later implementation. |

No applicable `AGENTS.md` was present at `/`, `/home`, `/home/oneadmin`, `/home/oneadmin/projects`, or either inspected plugin repo, and no nested `AGENTS.md` was returned by those repo scans. Every dispatched agent must check its actual worktree again. MCQQ has untracked `.cursor/` and `CLAUDE.md` in the source checkout; leave them untouched and do not silently treat old generated snapshots as fresh acceptance evidence.

These observations justify integration tasks. They do not establish every potential runtime defect. For example, a class claiming thread safety without a visible lock should be tested against its intended ownership model before a concurrency bug is reported. Existing WebSocket-library keepalive must be understood before adding another heartbeat mechanism.

## Four substantive jobs

| Job | Repository/worktree | Deliverable | Independent acceptance outline |
|---|---|---|---|
| A | MCQQ / `empirical/mcqq-command-policy` | Real RCON policy boundary, safe whitelist commands, batch execution with honest outcome handling | [A prompt and gates](empirical/job-a-mcqq-command-policy.md) |
| B | MCQQ / `empirical/mcqq-runtime-health` | Fresh/coalesced player queries and lifecycle-aware connection health/alerts | [B prompt and gates](empirical/job-b-mcqq-runtime-health.md) |
| C | QueQiao / `empirical/queqiao-resilience` | Interruptible capped reconnect policy, stable start/stop/reload, validated generated commands | [C prompt and gates](empirical/job-c-queqiao-resilience.md) |
| D | CodeNeuro / `empirical/codeneuro-evidence` | Receipt-backed experiment reports and evidence integrity validation | [D prompt and gates](empirical/job-d-codeneuro-evidence.md) |

A and B begin from the same pinned MCQQ commit in different Git worktrees and different CodeNeuro tasks/sessions. They must not see each other's short-term rules. Shared stable repository contracts can be visible to both. Changes to common lifecycle or handler files are merged deliberately after both independent task branches are inspected; rerun their combined integration cases after merge.

Each job has bounded useful milestones and a follow-up backlog. The agent is expected to investigate, implement, debug, test, review and revise actual code, with real reasoning/tool turns. Do not use a fixed prewritten patch generator, sleep loop, repeated passing test, or request replay to fill runtime or sample counts. Record actual active duration and external wait duration separately. If a job finishes before adequate evidence exists, root assigns an independently useful follow-up from the backlog or another justified requirement after inspecting current state. Do not redefine an incomplete task as success to meet a clock target.

## Dispatch and sampling protocol

1. Record job ID, repository identity and base commit, actual provider/model, real agent host/name, worktree path alias, task/session/worktree IDs, sidecar version, and start time. Secrets stay in process environment or protected operator configuration, not in the prompt.
2. Read applicable project instructions and establish baseline tests. Distinguish a preexisting failure from one introduced by the task. Upload the actual client-generated index. Analyze the PRD with the configured model and review candidate rules before making them active. Reject irrelevant/broad/duplicated candidates; there is no quota of P0 rules.
3. Use `codeneuro_read_file` and `codeneuro_edit_file` for task file reads/writes so context injection and edit preflight are observable. Use `codeneuro_run_tests` for real test commands with affected paths. Directory listings/searches can use native tools, but content access that bypasses the adapter must be logged as an instrumentation gap, not counted as an injected delivery.
4. Before a cross-file change, inspect the preflight result. Resolve `block` or `review` using the actual constraint/plan/evidence. Do not bypass the tool with an untracked shell write merely because it refused a change.
5. After a meaningful development step, rate actually seen rules using their delivery IDs. Use the documented scale: 0 already known, 1 irrelevant, 2 low quality, 3 neutral, 4 helpful, 5 essential. Explain the observed effect or interference. Never require score 5 or any particular distribution. Repeated feedback on the same receipt is not a new sample.
6. Record genuine failures and discoveries with source/test evidence. Update task rules only when the evidence supports the change; version changes made only to inflate counts are invalid. Report rule conflicts, missing scope, stale constraints or excess noise when actually encountered.
7. At milestones and final handoff, record commit/diff, tests, unresolved limits and the effect of retrieved rules. End with idempotent session cleanup; release/archive a task only after its code acceptance passes. Review distillation suggestions and verify the resulting long-term contract and short-term expiry using another actual access.

Aggregate target: **four substantive jobs, at least three repositories, at least 100 genuine context deliveries and 60 distinct `(project_id, rule_id, rule_version)` feedback pairs**. Also report distinct `(session_id, rule_id, rule_version)` pairs, total feedback rows and receipt duplicates so cross-session repeats cannot conceal low rule diversity. These are evidence targets, not instructions to manufacture calls or rules. Root must inspect actual receipt and tool logs before claiming the counts. If the data falls short, continue useful coding work rather than counting protocol fixtures.

Record natural coding usage separately from explicitly labelled diagnostic exercises (e.g. intentionally conflicting P0 plan, stale version, irrelevant fixture rule). Diagnostics can demonstrate failure handling; they must not inflate natural-use sample counts, score distributions, or claims that the framework improved task success.

## Independent review and artifact requirements

The implementer runs tests, but an independent reviewer chooses unseen edge cases from each acceptance outline, checks the runtime entry point, and verifies the final branch diff. Importing a helper or passing its unit tests does not prove it is used by the real path. Failure injection must target the production path while replacing only external transports/runtime services, and the report must name those replacements. A local loopback WebSocket exchange is real protocol evidence; it is not a deployed Minecraft/AstrBot compatibility claim.

Each private job bundle should contain a manifest, exact prompt, tool-call/event log, provider/model identity, repository commits and patch, baseline/final test results, relevant receipt/version feedback, issue/finding provenance and cleanup/distillation results. Record artifact hashes after collection. An operator-facing report links assertions to these artifacts and explicitly lists missing evidence.

Public or shared exports must omit bearer keys, API keys, passwords, raw environment, private absolute paths, user/chat/player identifiers, private conversations and unsanitized source/config excerpts. Preserve safe aliases, IDs/versions, timestamps, exit codes and hashes. Do not publish the raw SQLite database, auth config or agent transcript by default. Review the sanitized artifact set before pushing it. Synthetic benchmark fixtures and diagnosed counterexamples are labelled so they cannot be mistaken for actual user sessions.

## Performance measurement

`scripts/benchmark_context.py` creates a new temporary fixture database and starts a dedicated loopback HTTP server. It accepts no production URL/database argument. Default fixture: 1,000 rules, 100 distinct sessions, 1,000 HTTP context requests with 100 clients in flight. A second task's scoped rules are decoys used to verify isolation; their contents must never appear in task A deliveries.

The harness measures p50/p90/p95/p99 latency, throughput, errors, response sizes, CPU/RSS when available, observed client/server in-flight requests, durable receipt counts and database integrity. It reports machine/software/workload metadata and raw latency samples. Run a smaller smoke profile before the isolated 100-client profile. Report numbers as measurements on this host/workload; a configured concurrency value alone is not proof of observed server concurrency. The harness does not claim nanosecond matching or validate remote-network/Windows throughput.

Example (isolated fixture only):

```bash
PYTHONPATH=src python scripts/benchmark_context.py --rules 20 --requests 8 --concurrency 2 --output /tmp/codeneuro-benchmark-smoke.json
PYTHONPATH=src python scripts/benchmark_context.py --rules 1000 --requests 1000 --concurrency 100 --output /tmp/codeneuro-benchmark-100.json
```

Metrics use `schema_version:1`; the machine-readable contract is [benchmark-context.schema.json](benchmark-context.schema.json). Top-level keys are `kind`, `created_at`, `environment`, `workload`, `metrics`, `resources`, `validation`, `errors`, and `latency_samples_ms`. `kind` is `synthetic_isolated_http_benchmark`. A nonzero exit indicates request/correctness/integrity failure. Slow valid output remains useful evidence and is not relabelled as success against an unspecified performance promise.
