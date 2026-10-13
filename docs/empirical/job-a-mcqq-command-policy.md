# Job A: MCQQ command policy on the real execution path

Use the common dispatch/evidence protocol in `../empirical-tasks.md`. Root fills actual worktree/task/provider metadata externally. Do not put tokens into this prompt or contact the deployed game servers.

## User outcome

An authorized administrator can run allowed RCON operations, validated whitelist changes, and an explicitly supported batch without bypassing command policy or receiving a false success message. Disallowed commands fail before any network execution. Retries do not silently duplicate an operation whose outcome is unknown.

## Evidence to revalidate

At MCQQ `0b69c51`, `CommandHandler.handle_rcon_command()` enforces the existing administrator check then calls `RconManager.execute_command()`. That manager does not invoke `RconSecurityGuard`. `WhitelistManager` and `BatchCommandExecutor` have isolated tests but no identified live caller. The generic batch helper retries exceptions; a timeout after a remote write is not evidence that the write failed.

## Milestones

1. Trace the handler → manager → transport path and establish regression tests around it. Preserve existing administrator checks and the local RCON reconnect command (`重启`). Define explicit behavior for whitespace, leading slash, command aliases/namespaces, empty input and multi-line input. Explain which syntax the server accepts and what cannot safely be normalized.
2. Put the guard at a shared execution boundary, so direct manager calls, a batch and a whitelist operation use the same policy. Establish a stable per-server identity and bounded limiter state; avoid mixing two adapters' limits. Validate configuration values and document compatibility/default behavior. Do not install a global monkeypatch.
3. Implement an administrator-facing whitelist/batch path with strict structured input and truthful per-command outcomes. No arbitrary shell evaluation. Update whitelist state only after confirmed server success. Keep failed/unknown outcomes visible. Permit retries only for operations explicitly safe to retry, or for failures known to occur before sending; preserve cancellation and timeouts.
4. Exercise failures through the production handler/manager using a deterministic local fake RCON transport. Review logs for secret/raw-command disclosure, update operator docs, and keep all preexisting command and player-list regression cases passing.

## Independent acceptance

- A nonadministrator invocation produces zero transport calls. A prohibited command sent through each available entry point also produces zero calls. The local reconnect command is distinguished from a server restart command.
- Allowed read-only and configured write commands preserve response formatting and return real outcomes. Boundary forms (case, slash, repeated spaces, line breaks and supported namespaces) cannot bypass the chosen policy.
- Two server identities have independent limiter state. Concurrent requests cannot acquire more permitted capacity than the documented ownership/concurrency model permits. Invalid zero/negative/NaN configuration is rejected or normalized explicitly.
- Batch `abort` and `continue` policies produce ordered, complete results. A rejected command, transport disconnect before send, timeout after send, and cancellation are distinct. The timeout-after-send case is not automatically retransmitted as if no write happened.
- Invalid player names never reach transport. Failed add/remove leaves local whitelist state unchanged; successful changes are reflected for the correct server only.
- Runtime tests invoke production public entry points; helper-only tests do not satisfy this gate. No actual Minecraft server state changes occur during acceptance.

## Useful follow-ups if core work finishes early

Add bounded audit history with redaction and explicit configuration reload semantics; test reconnect races against queued commands; document safe migration of old configurations; add behavior for a batch interrupted after several confirmed commands without claiming atomic rollback. Choose only follow-ups still missing after inspection.

## Final handoff

Supply commit(s), baseline/final commands and outputs, entry-point call-chain evidence, new configuration docs, real CodeNeuro receipts/ratings/findings, and limits of the fake-transport integration tests. Do not call this a production deployment.
