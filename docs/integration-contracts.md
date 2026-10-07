# Parallel implementation contracts (working agreement)

Baseline: 3585670. Each implementation agent works in a separate git worktree; root integrates commits. No agent deploys production or touches credentials.

- Router factories accept the existing Storage instance and return FastAPI APIRouter. Root alone wires them into api.py. Do not hold SQLite transactions during provider/network I/O.
- Extension schemas use namespaced, transactional migrations and do not overwrite PRAGMA user_version or core schema. Implement an ensure_schema(storage) function per feature.
- Domain errors use DomainError/Conflict. All project/task/session identities must be checked before writes. Keep provenance and expected_version semantics.
- APIs return factual empty states; no seeded data. UI uses text nodes/escaping, checks errors and exposes pending/failed jobs.

## Intended UI endpoints

Existing /api/projects, /rules, /tasks, /worktrees, /sessions, /audit, /context remain available.

Intelligence router (owner intelligence; finalize schema with UI/root):
- POST /api/projects/{p}/index/local (registered server workspace)
- POST /api/projects/{p}/index/manifest (client-produced validated manifest)
- GET /api/projects/{p}/graph?path=...
- POST /api/projects/{p}/analysis (task_id, text, request_id) -> durable job
- GET /api/projects/{p}/analysis/jobs and GET /api/analysis/jobs/{id}
- POST /api/projects/{p}/distill (task_id, request_id) -> durable suggestions/job
- Expose reusable LLM structured completion/semantic preflight interface for governance/root.

Governance router (owner governance; finalize schema with UI/root):
- PATCH /api/tasks/{id}/pause and /resume (explicit paused state)
- POST /api/agent/rules (session-bound short-term create/activate)
- PATCH /api/agent/rules/{id} (session, expected_version, action/update/priority/reason)
- POST /api/agent/test-runs (actual command/result and evidence)
- POST /api/agent/sessions/{id}/cleanup (idempotent epilogue)
- POST /api/agent/preflight (files, plan, diff; return allow/block/review + evidence)
- POST /api/issues/{id}/apply-suggestion (reviewed structured change)
- GET /api/projects/{p}/governance (confidence/aging/observations/proposals)

Root:
- Authenticated remote-client identity and workspace registration; client-side file resolution/index/sync.
- GET /api/projects/{p}/events durable resumable SSE.
- GET /api/projects/{p}/inspector?path=...&task_id=...&days=7 (matched rules/provenance/delivery stats).
- POST /api/agent/sessions/{id}/bind-task (safe session boundary, expected binding revision).
- Actual coding run observation and receipt-backed rating collection.

UI must communicate schema needs early; owners publish DTO contracts, and root resolves integration conflicts. Additional routes are fine when required by the actual user workflows.
