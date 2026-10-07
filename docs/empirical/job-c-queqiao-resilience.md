# Job C: QueQiao reconnect lifecycle and generated-command validation

Use the common dispatch/evidence protocol in `../empirical-tasks.md`. Work only in the provisioned QueQiao worktree and loopback test environment.

## User outcome

The reverse WebSocket client reconnects with a documented capped backoff, stops promptly while waiting, and survives repeated start/stop/reload without orphaned resources. Existing remote message APIs validate their inputs before generating Minecraft commands, preserve protocol compatibility, and record factual outcomes.

## Evidence to revalidate

At `88ff7ae23426071b07c9651a65d86297795c97f4`, `ReconnectBackoff` is not called by `WebSocketClient.start()`, which uses a linear delay and `asyncio.sleep`. `stop()` clears `_should_run`, closes the current socket and logs a request; direct stop while asleep is not explicitly awakened. Plugin entry points also manage a thread/event loop and can force cleanup.

`ApiHandler` offers only broadcast/private/title/actionbar/player queries. It has **no general remote execute API**. `send_title()` interpolates timing inputs into server-generated `title` commands, and title/actionbar call `server.execute()`. `McdrCommandGuard` exists separately. Do not invent an arbitrary-command vulnerability or add an execute API just to connect that helper.

## Milestones

1. Specify retry semantics for handshake failure, rejected authentication, abrupt close and normal peer close. Integrate a bounded, validated reconnect policy using injectable clock/jitter or equivalent deterministic tests. Define reset only on the chosen successful-connection criterion, not on unrelated events.
2. Make stop interrupt connection attempts/backoff waits and await owned tasks predictably. Preserve cancellation. Integrate with plugin thread/loop start/stop/reload ownership so repeated lifecycle operations are idempotent and cannot operate on a replaced endpoint's loop.
3. Validate generated title/actionbar inputs: bounded integer timing fields, bounded message/component forms, correct JSON escaping and explicit rejection of unsupported data. Use a shared audited generated-command boundary if justified; preserve the existing limited API surface. No model-generated arbitrary command should be exposed.
4. Test actual client/server frames with a loopback listener, header authentication metadata, echo preservation, invalid input, peer closure, send/stop races, retry exhaustion and plugin reload. Improve config documentation/migration only where needed for the final design.

## Independent acceptance

- The observed retry schedule respects configured cap and jitter bounds, uses the documented maximum-attempt semantics, and resets after the specified success condition. Tests use controlled time for long schedules instead of sleeping to inflate runtime.
- `stop()` during a long backoff completes within an agreed short bound (e.g. under one second in the local test), leaves no live client task, and does not dial again. Start → stop → start and repeated stop remain valid.
- A normal close does not create an uncontrolled immediate reconnect loop. Authentication failure and temporary transport failure have explicit observable policies, without printing bearer headers or credential-bearing URLs.
- Headers and response echo retain established protocol semantics across the supported websockets version(s). A test should not mask a real TypeError inside `_on_connected` as evidence to retry an old connection-signature API.
- Invalid timing/message inputs cause zero `server.execute()` calls. Valid title/actionbar requests generate correctly escaped commands and preserve documented success/error response shapes. No general remote execute route is added.
- Runtime integration tests exercise the actual client and handler. Clearly state whether the MCDR host is stubbed; that test is not a live Minecraft deployment claim.

## Useful follow-ups if core work finishes early

Add endpoint-generation ownership for thread teardown races, configuration reload validation with no partial state change, bounded diagnostic counters, and documented dependency-version coverage. Choose real missing behavior, not repeated reconnect probes of an already-proven case.

## Final handoff

Provide commits, baseline/final test and actual WebSocket transcripts with secrets redacted, lifecycle ownership explanation, compatibility limits, and real CodeNeuro findings/ratings/cleanup artifacts.
