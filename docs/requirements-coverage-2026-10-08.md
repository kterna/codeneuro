# CodeNeuro current scope audit

This audit supersedes the 2026-10-07 snapshot. It is based on `feature/full-product`
at `9cb23fb`, the 175-test regression, the isolated remote MCP/HTTP tests, the
browser acceptance bundle, and the private empirical Hub records. It records
limits instead of treating a protocol fixture or a green unit test as proof of
an external deployment.

| ID | Current evidence | Remaining limit |
|---|---|---|
| R01 | Remote registry, project-scoped bearer clients, lexical Windows/Linux paths, and streamable HTTP MCP are implemented and covered by remote MCP tests. | The live NAS service still has no `CODENEURO_API_TOKEN`; production remote access is prepared but not enabled. |
| R02 | `.codeneuro.json` discovery, explicit trusted Hub pinning, native workspace identity, and `sync` CLI are implemented. | No Windows workstation has been run in this environment. |
| R03 | Project, worktree, task, session and client ownership checks have regression coverage. | None found in current test scope. |
| R04 | Client index manifests contain files, entities, calls and endpoint edges; real MCQQ, QueQiao and CodeNeuro indexes were uploaded. | Static analysis cannot resolve dynamic imports or runtime reflection. |
| R05 | Intelligence jobs use indexed graphs, configured provider output schemas, evidence locations and human candidate review; real provider samples passed. | The heuristic decomposer remains an explicitly offline fallback; no provider call is made without a configured provider. |
| R06 | Candidate review, expected versions and human audit records are implemented in API and workbench. | Drag-and-drop review is represented by scoped forms rather than a separate visual editor. |
| R07 | Release/archive and pause/resume lifecycle tests preserve long-term rules and expire task rules. | Distillation still needs human review before promotion. |
| R08 | Priority ordering, P0 retention, glob scope and character budget are implemented. | No explicit ScopeNode inheritance graph or model-token counter exists. |
| R09 | Codex, Claude, Hermes and pi adapters plus MCP sidecar are present; real coding jobs used receipt-bearing sidecar reads/edits/tests. | Native hook behavior was not verified on a Windows host or every installed agent version. |
| R10 | Cursor MDC and CLAUDE.md exports are atomic, UTF-8, ownership-aware and preserve human sections. | Workbench export entry is still CLI-driven. |
| R11 | Authenticated `sync --watch` polls authoritative snapshots, handles lag/outages, invalidates stale files and supports Windows locking. | No deployed cross-machine watcher has been observed. |
| R12 | Agent task-rule create/update/reduce-priority/revoke and evidence gates are implemented. | Long-term contracts remain human-reviewed by design. |
| R13 | Real test runs, failure reflection and recovery evidence are persisted. | Reflection quality depends on the agent supplying a useful failure analysis. |
| R14 | Cross-file preflight combines deterministic checks with graph-grounded provider assessment and refuses ungrounded P0 blocks. | It assesses the supplied plan/diff; it does not execute code. |
| R15 | Session cleanup is idempotent and records retained/revoked/promotion-review results. | Cleanup requires a reachable Hub at the time of the call. |
| R16 | Distillation requests, source references and human-reviewed merge proposals are persisted. | Automatic promotion is intentionally absent. |
| R17 | Evidence version, confidence, support/contradiction counts and half-life decay are implemented and shown in the workbench. | Confidence is an evidence estimate, not a correctness probability. |
| R18 | Workbench renders heatmap/tree data from live APIs. | No Windows browser session has been run. |
| R19 | Inspector returns file rules, delivery history and agent statistics; browser flows cover focus inspection. | Historical telemetry is limited to what agents actually recorded. |
| R20 | Swimlanes and pause/resume controls are in the workbench and API. | No separate drag-and-drop lane editor. |
| R21 | Workspace/session dashboard, current file, heartbeats and safe task binding are implemented. | Production remote workstation evidence is pending live admin authentication. |
| R22 | SSE event stream supports cursors, reconnect and live refresh. | A deployed browser reconnect under network interruption is not yet recorded. |
| R23 | Debug rating and issue tools are receipt-bound and session-scoped. | Natural coding runs currently contain 14 ratings and 11 distinct rule-version pairs. |
| R24 | Rule-quality API and Debug page show scores, noise, open issues and evidence. | The current run has fewer than the catalog target of 60 distinct feedback pairs. |
| R25 | Suggested issue actions are shown and require human-reviewed structured application. | No automatic rule mutation is performed from free text. |
| R26 | Version history, CAS updates, rollback and audit records are covered. | None found in current test scope. |
| R27 | Structural and semantic diagnosis endpoints preserve provider limitations and evidence clauses. | Model diagnostics remain advisory. |
| R28 | Tree/focus panes, swimlanes, command palette and live activity UI are present; browser acceptance passed. | Visual acceptance was on Linux Chromium. |
| R29 | Four substantive jobs across MCQQ (two worktrees), QueQiao and CodeNeuro produced commits, real MCP receipts, tests and feedback. B's lifecycle follow-up added commit `10b11a7` and a 43-test receipt-backed run. C's configuration reload follow-up added `34123c2` and a 50-test run. | The catalog target of 60 distinct feedback pairs is not met; the latest C follow-up had no token in its environment and therefore produced no new receipt, which is explicitly recorded rather than inferred. |
| R30 | Release archive and rollback script are prepared; current full-product source passes 175 tests. | Production replacement was rejected by automatic approval because it would restart the live service without explicit release authorization. |
| R31 | Isolated benchmark measured 1,000 rules, 1,000 requests, 100 observed concurrency, 25.03 req/s, p95 4.70 s, p99 5.98 s, zero errors and durable receipts. | These are Linux loopback fixture measurements, not Windows or WAN guarantees. |

## Empirical evidence

The private isolated Hub contains 319 context deliveries, 14 agent ratings, 11
distinct `(project_id, rule_id, rule_version)` pairs and test/issue/preflight
records. Job A committed `e175dac` and `863b992` with 37 tests; Job B committed
`b2351c8`, `3fac61d` and `10b11a7` with 40 and 43-test runs; Job C committed
`744d9ae` and follow-up `34123c2` with 49 and 50-test runs; Job D committed `3b0c55b` and `00095d1`, and its
integrated CodeNeuro regression passed 175 tests. A shareable receipt bundle was
exported and independently verified; it contains no tokens or private absolute
paths.

This audit leaves the goal active. The two concrete remaining gates are live
production authorization for the prepared release and more distinct natural
feedback pairs from useful coding work.
