# Repository intelligence and semantic review

The Hub can analyze a PRD against an immutable repository graph, propose scoped task rules for human review, and distill task knowledge into reviewed long-term contracts. A provider failure is a failed job. The offline heuristic extractor remains explicitly offline; it is never substituted for a successful model analysis.

## Provider configuration

Set these on the Hub process, using its existing secret management:

- `CODENEURO_LLM_BASE_URL`: compatible API base URL including the intended prefix, for example `https://provider.example/v1`.
- `CODENEURO_LLM_API_KEY`: provider credential, read only from environment. It is never returned by these endpoints or stored in jobs.
- `CODENEURO_LLM_MODEL`: the exact configured model ID.
- `CODENEURO_LLM_API_STYLE`: `chat_completions` (default) or `responses`.
- `CODENEURO_LLM_TIMEOUT`: request timeout in seconds, default 120, range 5–300.

Responses requests use `store=false`. Requests contain selected code signatures, docstrings, file headers, graph references, PRD, and relevant rule/finding text. The selected provider therefore receives those project details. Source files are not executed. HTTP redirects are not followed. Provider error bodies are not copied to the database, UI, or logs because they may echo credentials.

## Graph and remote manifests

The portable scanner is `codeneuro.indexing.build_manifest(root, *, max_files=5000, max_file_bytes=500_000, max_total_bytes=20_000_000)`. It supports Windows and Linux via `pathlib`, `os.walk`, and Git, with canonical relative POSIX paths in output. It reads Git-tracked and untracked nonignored files when Git is available, or walks ordinary directories. Generated/vendor directories, symlinks and symlink ancestors, `.env*`, credential/agent-private directories, credential filenames, binary/non-UTF-8, and oversized files are excluded. PEM private-key material is excluded. Git unavailable/truncation/parse limitations are explicit. Clients may reuse `is_indexable_path(path)` before opening a source file. This inclusion policy reduces accidental credential collection; it does not certify arbitrary source files as secret-free.

Python uses the AST for nested classes/functions, imports (including relative imports and aliases), calls, literal FastAPI/Flask decorators and local router prefixes. JS/TS/JSX/TSX/Vue/Svelte use labelled lexical extraction for components/functions/interfaces, imports, Express-style routes, and fetch/axios calls. Graph edges resolve local imports and imported Python symbols; endpoint edges connect literal frontend calls to matching backend endpoints. Reflection, runtime-generated routes, router mounting across modules, TypeScript type dispatch and dynamic aliases remain explicit limitations. The graph is evidence for a review, not proof of complete runtime connectivity.

Local indexing verifies the registered server project root or actual Git worktree. Remote clients generate the manifest on their machine and upload it; the Hub validates the registered project/worktree relationship, canonical paths, file hashes, ID derivation, source line bounds and size limits. The remote authentication layer must additionally enforce authenticated ownership of the worktree. A remote manifest is labelled `client_attested`; it cannot prove that a remote client's source content is honest. No server filesystem read follows a remote path.

Manifest shape:

```json
{
  "schema_version": 1,
  "git_commit": "optional commit",
  "files": [{
    "path": "backend/api.py",
    "language": "python",
    "sha256": "64 lowercase hex characters",
    "line_count": 20,
    "entities": [{
      "id": "ent_<derived hash>", "path": "backend/api.py",
      "kind": "function", "name": "checkout", "line": 4, "end_line": 20,
      "signature": "def checkout(payload):", "summary": "Finalize a cart."
    }],
    "references": [{"kind": "import", "target": ".service", "line": 1, "symbols": ["settle"], "bindings": {"settle": "settle"}}]
  }],
  "limitations": []
}
```

Use the scanner to produce IDs; they are SHA256 of canonical path, kind, name and line, separated by NUL, truncated to 24 hex characters and prefixed `ent_`. Endpoint entities add `method` and `route`. Reference kinds are `import`, `call`, `http_call`; HTTP calls add `method`, import references may include `symbols`, `bindings`, and `alias`.

Graph results contain `project_id`, `worktree_id`, `snapshot_id`, `created_at`, `source`, `trust`, `machine_name`, `git_commit`, `files`, `entities`, `edges`, `limitations`. Edges have `source`, `target`, `kind`, `path`, `line`, and reference edges add `resolved` and `confidence`. Unresolved references are retained and never presented as established connections. Identical manifests reuse the current snapshot ID. Old snapshots remain available for jobs referencing them.

## HTTP contracts

Mount `create_intelligence_router(storage)` into the existing application with its `DomainError` handler and normal auth controls. Start `router.intelligence_service.start_worker()` in application lifespan and call `stop_worker()` before closing Storage. The worker makes pending/expired jobs recover after restarts. POST routes also schedule immediate processing. Shutdown waits for an in-flight provider request within its configured bound.

| Method and route | Input / output |
|---|---|
| POST `/api/projects/{p}/index/local` | `{worktree_id}` → graph |
| POST `/api/projects/{p}/index/manifest` | `{worktree_id, manifest}` → graph |
| GET `/api/projects/{p}/graph` | Optional `worktree_id`, `path` → graph with matching files and adjacent edges/entities |
| POST `/api/projects/{p}/analysis` | `{task_id,text,request_id,worktree_id?}` → 202 job |
| POST `/api/projects/{p}/distill` | `{task_id,request_id,worktree_id?}` → 202 job |
| GET `/api/projects/{p}/analysis/jobs` | Up to 100 latest jobs |
| GET `/api/analysis/jobs/{id}` | Durable job and candidates |
| POST `/api/analysis/jobs/{id}/retry` | Failed job → queued, retaining original input/index |
| POST `/api/analysis/candidates/{id}/review` | `{action:approve\|reject,expected_version,title?,scope_patterns?,priority?,content_points?}` |
| POST `/api/projects/{p}/diagnostics/semantic` | `{worktree_id?}` → persisted semantic diagnosis |
| GET `/api/projects/{p}/diagnostics/semantic` | Up to 30 latest diagnoses |

Select `worktree_id` explicitly if a project has multiple workspaces. Jobs use `queued`, `running`, `completed`, `failed`. A job includes `id`, `project_id`, `task_id`, `worktree_id`, `kind`, `request_id`, `snapshot_id`, `attempts`, timestamps, `error`, `result`, `candidates`. Request IDs are unique per project: identical retries reuse the job; different caller inputs conflict. The immutable job input includes the task, current contracts/findings, and index snapshot. Reindexing does not silently change an existing job. Analysis requires an active/testing task. Distillation also accepts released/archived tasks.

Job `result` includes `summary`, `uncertainties`, `provider`, `usage`, `limitations`, `candidate_count`. Candidate fields:

- Identity/state: `id`, `job_id`, `version`, `status` (`pending`, `approved`, `rejected`), `rule_id`, `reviewed_at`.
- Proposed rule: `title`, `scope_patterns`, `priority`, `content_points`, `rationale`.
- Grounding: `evidence:[{entity_id,path,line}]`, `source_rule_ids`, `source_finding_ids`.
- Distillation behavior: `action:create|merge|discard`, optional `target_rule_id` and `target_rule_version`.

Every model candidate must cite a real entity in the graph actually sent to the model and match at least one indexed path. Every task rule must be accounted for by distillation. The model can explicitly propose discarding temporary knowledge. The Hub creates no active rules until approval. Analysis approval creates a task rule; distillation approval creates or updates a long-term contract. A merge updates the named contract using its exact analyzed version, preserving normal core version history. Human edits during review are included in the same transaction. Concurrent changes, already-reviewed candidates, or inactive analysis tasks reject approval. Source candidates and audits retain provenance even after merging. No source task history is deleted.

## Durable execution

Tables are namespaced `cn_intel_*`. `ensure_schema(storage)` is transactional and does not change core `PRAGMA user_version`. Each job claim writes a unique lease token and 10-minute expiration. Other workers skip live leases. After a crash, an expired lease can be reclaimed; only the current lease holder can commit the result. Candidate creation, result state and audit commit atomically. Provider calls run outside Storage transactions. A retry can repeat an external model request if the process died after the provider replied, but cannot apply duplicate rule mutations: candidates require separate optimistic human approval. The outbound request uses the stable job ID as idempotency key when the provider honors it.

## Semantic assessment interface

```python
service = IntelligenceService(storage, provider=None)
verdict = service.semantic_assess(
    project_id, files=["backend/api.py"], plan="...", diff="...",
    rules=applicable_rule_models, worktree_id=worktree_id,
)
```

The result contains `decision:allow|block|review`, `assessments`, `rules_checked`, `violations`, `reasoning`, `limitations`, `provider`, and `snapshot_id`. Every supplied rule must be assessed exactly once at its exact version. A violation must quote actual plan/diff text. Evidence references must exist in the supplied graph. Only a grounded P0 violation yields `block`; uncertainty or lower-priority violations yield `review`. No matching rule or model statement proves general software correctness. The governance caller must persist input/verdict and revalidate current rule and session versions before applying changes. Provider/missing-index errors are explicit `DomainError` values, never `allow`.

`service.diagnose(project_id, worktree_id=...)` performs semantic consistency review of active applicable project rules. Every returned conflict must quote real clauses from at least two distinct rules with overlapping indexed scope and compatible task domains. Results carry `assessment_type:model_semantic_review`; they are separate from structural facts, do not invent a health score, and do not mutate rules. Provider failures remain visible.

The prompt graph is bounded by entity/file/edge character budgets; omitted content is reported. These are bounded serialized context budgets, not a claim of exact provider token counting. Model JSON is validated strictly; malformed output, missing source coverage or invented evidence produces a failed job for inspection/retry.

## Verification boundary

`tests/test_intelligence.py` exercises actual SQLite persistence, thread/process-equivalent separate connections, index snapshots, provider boundary wire schemas with injected HTTP transport, exact evidence validation, reviewed merges and HTTP routes. The injected provider is test-only; these tests do not establish live model quality. Production acceptance requires the configured provider to analyze real PRDs, semantic positive/negative cases, and task distillation, followed by the long coding experiments owned by the main integration track.
