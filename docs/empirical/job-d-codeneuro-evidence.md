# Job D: CodeNeuro experiment evidence export and verification

Use the common dispatch/evidence protocol in `../empirical-tasks.md`. Root supplies a worktree at the integrated product commit and an isolated experiment database. Do not migrate, stress, or edit the production database.

## User outcome

An operator can export and independently validate an experiment report showing what each real coding agent actually received, rated, changed and tested. Counts must be backed by delivery/version receipts, and legacy/demo/diagnostic data must not be presented as natural coding evidence. An incomplete chain remains visible instead of becoming a polished success claim.

## Evidence to revalidate

Core tables include `agent_sessions`, `context_deliveries`, `delivery_rules`, `rule_evaluations`, `rule_versions`, `audit_events`, findings and task/worktree identity. Some earlier records were explicitly marked `legacy` or `demo`. New governance/intelligence tables add tests, preflight, proposals and jobs; inspect the actual integrated schema and public interfaces rather than assuming table names from a plan. The existing Debug lists/statistics are not a complete portable experiment proof bundle.

## Milestones

1. Design a versioned evidence manifest with explicit natural/diagnostic/synthetic/legacy categories and read-only data access. Define receipt-backed counting semantics and what the exporter can/cannot verify about an external agent process or Git artifact. Keep core migrations untouched unless a reviewed additive schema is necessary.
2. Implement an operator export entry point with project/task/session/time filters and deterministic JSON plus a concise Markdown report. Capture a consistent SQLite snapshot without modifying the source. Include rule versions actually delivered, score reasons, issue/finding/test references, task state and missing evidence. Bound output sizes and support useful errors/cancellation.
3. Implement an independent bundle verifier that checks manifest hashes, referential links, duplicate receipt-feedback keys, cross-session/project/task contamination, rule-version existence, chronology and declared artifact availability. Aggregate distribution/sample counts only from eligible real receipts; expose duplicate and excluded rows separately. Never infer a real provider invocation from an agent label alone.
4. Build realistic fixture cases from schema-supported records, including intentional corruption/missing links, then validate a private real experiment export provisioned by root. Do not hardcode the desired 100/60 counts. Reopen the bundle in a separate process and verify that its conclusions are reconstructible without the original database.

## Independent acceptance

- Export against a source opened read-only leaves database content/schema unchanged. Concurrent producer writes do not yield a partially inconsistent bundle; the snapshot boundary is explicit.
- Every included rating resolves to an actual delivery owned by the same session, a delivered rule/version and its historical content. A current rule edited after the delivery does not rewrite the old evidence.
- The report separately counts deliveries, feedback rows, distinct `(project,rule,version)`, distinct `(session,rule,version)`, sessions, repositories and active durations. Idempotent retries and legacy/demo/diagnostic fixtures do not inflate natural-use totals.
- Missing Git/test/provider artifacts are reported as unknown or incomplete. A successful HTTP/tool call cannot by itself prove the model used a rule to improve code quality. Scores and negative feedback are preserved; no normalization to a target score is applied.
- Removing a delivery, changing a cited version, changing an artifact hash or attaching a receipt to another session makes verification fail with a precise actionable error. An intentional diagnostic remains excluded even if its content resembles a normal rule.
- Default shareable output omits tokens/passwords/raw environment, private absolute paths and private chat/player/user identifiers. Redaction/aliasing is deterministic within the bundle and preserves joins. The private full bundle, if supported, requires an explicit option and is clearly labelled.
- CLI/API behavior is documented and tested through its entry point. Root reviews any API/CLI wiring that overlaps the integration track before merging.

## Useful follow-ups if core work finishes early

Add comparison between two genuine cohorts with sample-size caveats, resumable export for large histories, schema-version compatibility tests and optional SQLite integrity-check evidence. Improve query performance only from a measured bottleneck using the isolated benchmark fixture. Do not fabricate scores or add fake sessions to make a demonstration attractive.

## Final handoff

Supply commits, schema/format documentation, verification commands, fixture corruption outcomes, a sanitized example explicitly labelled synthetic and a separate private real-run report when available, plus actual CodeNeuro feedback about developing this feature.
