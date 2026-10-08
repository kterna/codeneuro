# Receipt-backed experiment bundles

`codeneuro evidence-export` reads an existing SQLite database in read-only mode and
publishes a new portable directory. `evidence-verify` reopens that directory in
another process, checks member hashes, reconstructs summary counts, and validates
receipt, session, project, task and historical rule-version links.

```bash
codeneuro evidence-export --db /path/state.db --project-id PROJECT \
  --classification /path/reviewed-sessions.json --out /path/new-bundle
codeneuro evidence-verify --bundle /path/new-bundle
```

`--task-id`, `--session-id`, `--since` and `--until` narrow the snapshot. The
timestamps are ISO 8601. Time filters apply before row limits to delivery,
feedback, test, finding, issue and preflight events; historical rule versions
remain as supporting evidence. Issue rows lack a historical task ID, so a
task-filtered export omits them and source-declares the omission count; the
portable verifier cannot reconstruct that count without the database. The output
directory must not exist. A single SQLite read transaction provides the
snapshot; the source database is never opened by `Storage` or migrated. A 50 MB
limit per bundle member and a 50,000 row limit per selected table return an
explicit error instead of silently truncating evidence. Queries
are batched for older SQLite parameter limits on Windows.

## Classification and counting

The exporter does not infer natural coding from an agent name or a test result.
Provide reviewed session labels when there is an external, content-free tool log:

```json
{
  "sessions": {
    "actual-session-id": {
      "category": "natural",
      "tool_log_sha256": "64 lowercase hex characters"
    },
    "diagnostic-session-id": {"category": "diagnostic"}
  }
}
```

Valid categories are `natural`, `diagnostic`, `synthetic`, `demo`, `legacy` and
`unknown`. Missing labels are `unknown`. A worktree already marked `demo` or
`legacy` keeps that category even if the external label claims `natural`.
`natural` counts require both the reviewed label and actual receipt-backed agent
rows. The bundle preserves all scores, including negative scores. Retries of
the same receipt/rule pair are checked for duplication. Distinct
`(project, rule, version)` and `(session, rule, version)` counts are reported
separately. The tool-log hash is operator declared; the portable bundle cannot
authenticate an external coding-agent process or a provider call.

## Privacy and verification boundary

The default bundle aliases identifiers and hashes relative file paths, client
reported repository identities, rule content, feedback reasons, agent names
and branches. It omits credentials, raw
environment, source excerpts, test output and private absolute paths. Use
`--private` explicitly to include historical rule content and rating reasons;
keep that directory private and review it before sharing. The exporter creates
files with owner-only permissions. External Git patches, prompts, test logs and
provider transcripts are not bundled or verified automatically; the report
leaves those claims unresolved.

The verifier rejects altered members, broken rule-version and rating links,
cross-session/project/task references, duplicate feedback pairs, invalid
chronology and symlinked bundle roots or declared members. SHA-256 checksums detect edits but do not
establish authorship or source-database provenance. A successful tool call or
test row records what was reported; it does not establish that a model used a
rule or that a live deployment passed.
