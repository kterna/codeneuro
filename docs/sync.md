# Remote static rules: one-shot and watch synchronization

`codeneuro.sync.StaticSync` turns the current authenticated remote session's rule snapshot into Cursor MDC files and/or the managed section of `CLAUDE.md`. The shared `RuleExporter` owns output formatting and file locks. The sync layer owns remote scope reconciliation, change detection, stale-state handling and progress reporting.

The Hub's `export_rules` RPC returns:

```json
{
  "project_id": "authorized-project",
  "task_id": "currently-bound-task",
  "binding_revision": 2,
  "rules": []
}
```

The current session task and binding revision are authoritative. The synchronizer does not repeatedly substitute the original `.codeneuro.json` task for a session that was safely rebound. It rejects wrong-project rules, duplicate IDs, inactive rules and temporary rules belonging to another task. Paused/released/archived tasks cease contributing their temporary rules when the Hub excludes them from the scoped snapshot.

## Library and CLI wiring

Use the existing native workspace configuration and trusted Hub pin to create a dedicated `RemoteClient`. Give the sync client a bounded network timeout (5–10 seconds), rather than inheriting the 130-second model-preflight timeout. A stop signal interrupts polling waits immediately; an already-running HTTP call finishes or reaches that configured timeout before stopping.

```python
import threading
from codeneuro.client import RemoteClient, discover_config
from codeneuro.sync import StaticSync

client = RemoteClient(discover_config('/work/repo'), '/work/repo', timeout=5)
sync = StaticSync(client, formats=('cursor', 'claude'), poll_interval=2,
                  max_backoff=30, status_callback=print)

# Single export: inspect result['state']; 'stale' is a failure, not a success.
result = sync.sync_once()

# Long-running CLI mode: wire SIGINT/SIGTERM to stop.set().
stop = threading.Event()
sync.watch(stop)
client.close()
```

`formats` accepts `cursor`, `claude`, `both` or a tuple of the selected formats. `sync_once()` leaves the reconciled snapshots present. `watch()` synchronizes immediately and then polls. The root CLI owns `sync --watch` argument parsing, signal registration and a nonzero exit for failed one-shot sync.

The implementation deliberately declares `transport: "poll"`. It uses the authenticated project/session RPC with bounded polling instead of claiming an unimplemented SSE subscription. A project event stream can wake a future implementation earlier, but full snapshot reconciliation after reconnect is still required. A delivered event by itself is not proof that a particular task's rules are current.

## Real changes and race handling

The fingerprint contains exported fields, rule IDs/versions, task ID and binding revision. Live hit/feedback counters are excluded because they do not change instructions. Unchanged snapshots are not rewritten. Deleted generated files are regenerated on the next successful reconciliation.

After publishing a changed snapshot, the synchronizer fetches again. If scope/rules changed while files were being written, it invalidates the stale managed snapshot and retries with the new authoritative state. Three repeated races produce visible stale status instead of a false successful result. One worktree has one watcher lease across processes; Unix uses `fcntl`, Windows uses `msvcrt`. The exporter separately serializes each output mutation.

## Outage and stop behavior

On a transport error or invalid snapshot, the synchronizer immediately invalidates its managed snapshots. Cursor's managed files are removed through its ownership manifest. The `CLAUDE.md` managed block becomes an empty snapshot while human prose remains. This prevents an expired rule or previous task's instructions from silently surviving an unobserved remote transition.

Retries use bounded exponential backoff and always fetch the complete scoped snapshot. When the Hub returns, current rules are regenerated. On watcher stop, managed snapshots are invalidated by default because future Hub changes will no longer be observed. An embedding may explicitly choose `invalidate_on_stop=False` to retain a one-time snapshot; its status still says stopped.

The watcher does not close the coding agent's Hub session. Stopping static synchronization is not a claim that the coding task or session finished.

## Human content and errors

Files outside `.cursor/rules/.codeneuro-manifest.json` are preserved. Human text outside the `CLAUDE.md` markers is preserved. A generated filename colliding with an unowned file is refused. Malformed ownership paths/markers and symlinks are refused. Hashes of managed content are recorded separately; manual edits inside generated sections are preserved and reported as conflicts, rather than overwritten or silently deleted.

A conflict can prevent stale-file removal. The status then has `managed_snapshots_valid: false` and a non-null `invalidation_error`; it must not be displayed as a successful invalidation. Reconcile the local manual edit and retry. The status file contains no bearer credential or rule content.

`<workspace>/.codeneuro/sync-status.json` and the optional status callback expose:

- `state`: starting/current/stale/stopped; `watching` says whether automatic updates continue.
- `last_attempt_at`, `last_success_at`, `lag_seconds`, `next_retry_seconds`.
- `transport`, polling interval, project/task ID and binding revision.
- `rule_count`, output files, fingerprint and whether this iteration changed files.
- `managed_snapshots_valid`, safe exception-class `error`, and `invalidation_error`.

## Validation

`tests/test_sync.py` writes real temporary MDC/Markdown files and verifies initial scope, task switching, task expiry, raced binding changes, outages/recovery, human content preservation, conflicting manual edits, ownership errors, deleted-file regeneration, watcher cancellation and process-level exclusion.

The integration test also starts an actual loopback FastAPI/uvicorn Hub with a temporary SQLite database and private random administrator credential. It enrolls a project-scoped client over HTTP, uses the real `RemoteClient`, exports task A, changes the session to task B, then archives task B and confirms the temporary instructions disappear. It checks that the status file contains no client token. The test is skipped on a branch lacking the remote client, and runs against the complete integrated source.

Linux verification against the authoritative full-product tree: **11 tests passed**, including actual authenticated HTTP. Windows support uses native Python paths and Windows locking branches inherited from the exporter; a real Windows runtime remains a separate acceptance gate.
