# Job B: MCQQ player-query freshness and connection health

Use the common dispatch/evidence protocol in `../empirical-tasks.md`. This job uses a separate MCQQ worktree/task from Job A. Do not read Job A's task rules or modify its branch.

## User outcome

Repeated player-list queries avoid redundant remote work while reflecting joins/quits, disconnects and reconnects promptly. Connection status and alerts describe actual lifecycle events and do not misclassify a healthy idle socket. Unloading the plugin closes resources without leaving background tasks or API waiters hanging.

## Evidence to revalidate

At `0b69c51`, `PlayerListCache` is a standalone helper; the actual command path calls `get_player_list` on every request. Join/quit handlers are in `MinecraftPlatformAdapter`; correlated API waiters are already registered before sending and cleaned in `finally`. `WebSocketWatchdog` and `AlertDispatcher` are standalone helpers. The real WebSocket code already configures library ping/pong keepalive; a second watchdog must integrate with actual transport evidence instead of counting scheduler ticks as missed pongs.

## Milestones

1. Trace actual player-list command, response correlation and adapter event/lifecycle paths. Add integration tests proving existing behavior before changing it. Define cache identity (adapter/server + connection generation), TTL and unknown/error semantics.
2. Integrate bounded caching and concurrent miss coalescing into the real query path. Cache only valid successful data. Invalidate on observed join/quit, connection replacement/disconnect and relevant configuration change. A late response from an old connection must not repopulate a new generation's cache. Preserve correct empty-list results.
3. Integrate or replace the standalone watchdog with an owned, cancellation-safe lifecycle component backed by actual ping/pong or transport liveness signals. Reuse the library keepalive where appropriate; do not start competing heartbeat loops. Route factual disconnect/recovery transitions to an alert dispatcher with bounded deduplication and clear attempted/delivered/failed outcomes.
4. Exercise two adapters on a real loopback WebSocket listener, out-of-order responses, an unresponsive connection, and shutdown while a request is pending. Keep the root's instrumentation and production services untouched. Document configuration, event semantics and where external runtime objects are replaced by test doubles.

## Independent acceptance

- Two simultaneous player-list requests for one server coalesce to one successful remote request and receive equivalent independent results. Another server is unaffected. Mutating a returned list cannot corrupt cached data.
- TTL expiration, a join event, a quit event, a reconnect and connection replacement force the next query to fetch fresh state. Failed/malformed responses never become successful cache entries. Empty player lists remain cacheable if valid.
- An old in-flight result arriving after invalidation does not overwrite newer state. Cancellation of one waiter does not cancel unrelated waiters or strand the shared fetch.
- Real ping acknowledgement keeps an idle connection healthy; elapsed monotonic time and actual missing acknowledgement trigger at most one disconnect transition per generation. A scheduled tick alone is insufficient evidence of a lost heartbeat.
- Disconnect/recovery emits the documented alert transitions with no storm of duplicate sends. Sender failure remains observable and follows the documented retry/dedup policy; the component does not report successful delivery after swallowing an exception.
- Unload/close cancels owned tasks, completes or cancels pending API waiters, and permits a subsequent clean startup. Tests inspect task/socket lifecycle, not only a status boolean.
- The existing shared reverse-server routing/authentication, response-echo correlation and formatting cases still pass.

## Useful follow-ups if core work finishes early

Expose bounded operational counters for cache hits/coalescing/invalidation and real disconnect causes; add stress tests that target one suspected race rather than rerunning green tests; cover adapter configuration reload and shared-listener reference counting; document a reproducible troubleshooting sequence.

## Final handoff

Supply commits, actual protocol/test artifacts, freshness and lifecycle state diagrams if useful, remaining external-runtime limitations, and genuine receipt-backed feedback. Do not claim a fake player's presence or a production WebSocket connection as telemetry.
