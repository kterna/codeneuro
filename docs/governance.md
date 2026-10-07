# Rule governance and evidence contract

`GovernanceService` is the shared domain implementation for HTTP, MCP and clients. Its tables use the `governance_` namespace, transactional initialization and a separate extension version. Core `PRAGMA user_version` is untouched. All durable rule mutations, snapshots, source references and audits commit together.

## Temporary knowledge during coding

`POST /api/agent/rules` accepts `session_id`, `title`, `content_points`, `scope_patterns`, `priority`, `reason`, optional `activate`, `evidence_ids` and `half_life_days`. The current session fixes project and task; the caller cannot nominate an unrelated project or task. New agent knowledge is initially a draft observation. It can become active without human intervention after two distinct successful test reports, explicitly linked through `/api/agent/rules/{id}/observations`. Both observations must be from this session, target the current task, cover at least one path in the rule scope, and have no contradicting observation. Activation also requires effective confidence of at least 0.6.

`PATCH /api/agent/rules/{id}` requires `session_id`, `expected_version`, `action` and `reason`. Actions are `update`, `activate`, `reduce_priority` and `revoke`. Updates may contain `title`, `content_points`, `scope_patterns`, `priority`. Editing a proposition or raising its priority invalidates evidence about the previous proposition; active agent edits return to observation. New validation must come from test reports collected after that revision. Reducing priority or changing status preserves evidence about unchanged content. All transports, including manual rule edits, invalidate old evidence through the storage revision hook. Long-term contracts use human-reviewed proposals.

Confidence is the explicit evidence estimate `(1 + supporting observations)/(2 + supporting + contradicting observations)`. Effective confidence applies `0.5 ** (age_days/half_life_days)`. This quantifies the available evidence, not the probability a statement is true. Aging flags stale rules for review; it never silently removes P0 or human-authored contracts. `GET /api/projects/{p}/governance` exposes counts, exact observations, the original evidence version, age and policy.

## Test failure and recovery

`POST /api/agent/test-runs` accepts exactly:

```json
{
  "session_id": "session-id",
  "request_id": "stable-run-id",
  "command": ["python", "-m", "pytest", "tests/test_unit.py"],
  "exit_code": 1,
  "stdout": "bounded process output",
  "stderr": "bounded process output",
  "started_at": "2026-10-07T12:00:00Z",
  "finished_at": "2026-10-07T12:00:01Z",
  "paths": ["src/unit.py"]
}
```

Commands are argv arrays, preserving Windows and Linux compatibility. The Hub records `source=client_reported`; it does not claim to have executed the command. The client adapter owns actual execution and full artifacts. Reusing a request ID with different input conflicts. Replaying identical evidence under another request ID does not manufacture an extra sample.

Two consecutive failures of the same argv in one session/task create a reflection record. A later successful run records recovery and a scoped finding containing the actual evidence IDs. The observation explicitly does not establish root cause. `POST /api/agent/reflections/{id}` with `{session_id, analysis}` attaches the agent's explanation separately. A following context read returns this finding. Delayed older test reports cannot rewrite an already observed recovery.

## Pause, close and completion

`PATCH /api/tasks/{id}/pause` and `/resume` require `{reason}`. Pause stores the previous active/testing phase and immediately removes temporary rules from context eligibility. Resume restores that exact phase without rewriting rule content or versions.

`POST /api/agent/sessions/{id}/cleanup` accepts `{request_id,close}`. It revokes unvalidated drafts, retains validated active task knowledge, lists promotion review candidates and queues task distillation. Retrying a completed epilogue is idempotent. A checkpoint with `close=false` may be followed by a final epilogue, which also processes knowledge created since the checkpoint.

Storage task transitions to released/archived atomically expire active temporary rules and enqueue durable distillation requests. The host must call `process_pending_distillations()` from its background lifecycle worker. It dispatches the intelligence service's durable `distill` jobs outside SQLite transactions, pins a task session worktree, handles crashes by stable request ID, and exposes downstream queued/running/completed/failed states. A missing workspace/index produces visible `dispatch_failed`; it is retried when prerequisites are available. A failed provider job remains failed until explicitly retried through the intelligence workflow. Semantic candidates remain subject to human review.

## Reviewed structured changes

`POST /api/projects/{p}/governance/proposals` accepts:

```json
{
  "reason": "Why this knowledge should survive the task",
  "task_id": "optional-source-task",
  "change": {
    "action": "merge",
    "rule_id": "existing-contract-id",
    "expected_version": 3,
    "title": "Existing contract",
    "content_points": ["Exact reviewed final contract text"],
    "scope_patterns": ["src/**"],
    "priority": "P1",
    "source_rule_ids": ["temporary-source-id"]
  },
  "source_refs": [{"kind": "rule", "id": "temporary-source-id", "version": 2}]
}
```

Actions are create/update/merge/revoke. Create produces a new long-term contract. Merge updates an existing long-term contract, preserving its identity and creating a new version. Sources are checked against the same project and pinned versions. Review is `POST /api/governance/proposals/{id}/apply` with `{reviewed:true,reviewer,reason}`; stale source/target versions conflict. Applying once and retrying cannot duplicate the rule. Rejection is `/reject` with `{reviewer,reason}`.

`POST /api/issues/{id}/apply-suggestion` accepts the exact structured `change` plus the review fields. Applying the change, creating provenance and resolving the issue is one transaction. Natural-language `suggested_action` is never interpreted as executable instructions. The host's authentication layer must reserve all human review/policy routes for the administrator; a Boolean review acknowledgement is not authentication.

## Preflight evidence

`POST /api/agent/preflight` accepts `{session_id,request_id,files,plan,diff}`. `files` names proposed changed paths. Diff paths are normalized and included even if omitted from that list. The service loads all applicable active contracts and task rules, calls the intelligence semantic assessor outside transactions, and stores the exact inputs, rule versions, provider assessment and decision. A grounded P0 violation can block based on an exact plan/diff excerpt and repository citation. Unsupported model assertions and provider outages return review. Legitimate plans may return allow when all applicable checks have actually run. A rule/task change while inference is running, or before replaying an old receipt, returns review with a stale marker.

Administrators can bind an explicit machine policy to a specific rule version through `POST /api/rules/{id}/policy` with `{expected_version,reviewed:true,reviewer,spec}`. Supported kinds are `forbid_path_changes`, `forbid_added_literal`, `require_added_literal`; literal checks only inspect supplied added diff lines. Missing diff coverage is unverified. These explicit policies complement semantic assessment; natural-language contracts are not secretly translated into keyword checks. The result never certifies runtime code or replaces tests.

## Validation

`tests/test_governance.py` covers the lifecycle, stale evidence, project/task isolation, actual subprocess failure/recovery, scoped finding retrieval, replay and concurrency, reviewed merge provenance, atomic issue rollback, HTTP DTOs, semantic P0 verdict handling and explicit policy evidence. Fake semantic responses in unit tests validate orchestration only. Actual model judgments and long coding runs require the separate integration trial and must retain provider calls and receipt-backed feedback.
