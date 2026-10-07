# Real provider intelligence acceptance

`scripts/live_intelligence_probe.py` is a separate acceptance driver. It uses the actual `CompatibleProvider`, selected safe files from actual CodeNeuro and MCQQ repositories, and a new isolated SQLite database. It does not manufacture model JSON or substitute heuristic output. A provider/model/schema failure remains visible in the report and durable job state.

No provider call should be launched until the operator has supplied the intended private environment. The required variables are `CODENEURO_LLM_BASE_URL`, `CODENEURO_LLM_API_KEY`, and `CODENEURO_LLM_MODEL`; `CODENEURO_LLM_API_STYLE` selects `responses` or `chat_completions`. Configuration is checked before reading repository sources. Missing configuration exits with code 2 and `configuration_error`; it is never a passing result. The script never prints the key or a raw provider response body.

## Samples and boundaries

Collect performs these real provider cases:

1. A CodeNeuro PRD without source paths, grounded in selected actual context/storage/API code. The result must contain real candidate citations to the immutable graph sent to the provider.
2. An MCQQ PRD without source paths, grounded in the actual administrator/manager/guard/batch/whitelist code. It must propose review candidates using actual file/entity locations.
3. A task distillation case: a declared fixture refinement should merge into an existing scoped long-term RCON policy contract, preserve its original intent and cite the exact target version and task source. If the model proposes another action, the expectation fails honestly; the driver does not rewrite its output.
4. A compatible plan that checks authorization and deny policy before sending should produce `allow` against the explicit P0 rule.
5. A contradictory send-before-policy plan should produce `block` with actual quoted plan evidence and the correct rule version.
6. Contradictory scoped contract fixtures should yield a persisted semantic diagnostic citing both real rule records and their literal clauses.

The contracts/plans in cases 3–6 are **labelled acceptance fixtures**. Their rows and IDs really exist in the isolated database, and the model calls are real, but they are not observations from completed coding work. No game server is contacted. The intentionally contradictory contract is revoked after diagnosis. These samples are excluded from the long coding experiment's natural-use rating and delivery counts.

A seventh case deliberately removes the provider key within this isolated script process, queues another real job, and checks that the real provider boundary leaves it failed with no candidates. This is labelled `local_configuration_failure_diagnostic`, records that an HTTP request was not possible, and does not pretend to be a failed upstream response. The key is restored in `finally`; the caller's environment is unaffected.

## Collection

Run with an empty private directory after the operator has supplied provider environment. No credentials belong in shell arguments, prompts, tracked files, or output JSON.

```bash
PYTHONPATH=src python scripts/live_intelligence_probe.py \
  --phase collect \
  --run-dir /tmp/codeneuro-live-probe-run-001 \
  --codeneuro-root /path/to/integrated/codeneuro \
  --mcqq-root /path/to/astrbot_plugin_mcqq
```

Use `PYTHONPATH` for the implementation under acceptance; the script records its own hash, source commit/dirty flags and selected file SHA256 values. The shared scanner filters credential/private directories, sensitive filenames, symlinks/ancestors, binary and oversized files, and PEM private-key content. Only the published `SELECTIONS` paths are retained in the graph sent to the provider. Repository selection limitations are explicit; this is not a full-repository semantic coverage claim.

The run directory contains `isolated.db`, `report.json`, `provider-calls.json`, and `review-template.json`. Directory/file permissions are restricted where supported. Each provider receipt includes a real request ID, stage, model/API style, timings, usage when returned, input/output hashes and success/failure state. Structured job/candidate/semantic results contain the actual graph snapshot, entity, rule/version, job and candidate IDs. No raw HTTP response body is persisted by the probe. The private database still contains selected source metadata and absolute registered workspace paths; do not publish it as a sanitized artifact.

Collect exits 3 with `awaiting_review` when model cases pass but candidate review has not occurred. It exits 1 if an acceptance case fails. A schema error is useful failed evidence, not permission to replace a model result with a fabricated one.

## Explicit review

Inspect each candidate's text, scope, priority, rationale and citations against its source snapshot. Copy and fill `review-template.json` with actual decisions:

```json
{
  "reviewer_kind": "operator_agent",
  "reviewer_id": "actual-reviewer-label",
  "decisions": [{
    "candidate_id": "actual candidate ID from this run",
    "action": "approve",
    "expected_version": 1,
    "reason": "Specific reason based on the inspected proposal and evidence."
  }]
}
```

Every collected candidate needs a decision; reject poor proposals rather than approving them to make a gate pass. Allowed optional edits are `title`, `scope_patterns`, `priority`, and `content_points`. A declared human review uses `reviewer_kind:human`; an automated operator reviewer must use `operator_agent`. The report records this declaration and does not claim a human was present for an operator-agent run. Reviewer identity is an operator attestation, not cryptographic proof of a person's identity.

```bash
PYTHONPATH=src python scripts/live_intelligence_probe.py \
  --phase review --run-dir /tmp/codeneuro-live-probe-run-001 \
  --review-decisions /private/operator-decisions.json
```

Review makes no provider calls. The batch uses actual `IntelligenceService.review` and core optimistic versions in one SQLite transaction. It saves new rule versions, real audit sequences and the operator's reasons. The review gate requires at least one approved actual candidate from each PRD job and an approved merge that advances the existing contract to version 2. A legitimate rejection can therefore leave acceptance failed; it should lead to a prompt/product correction and another explicitly recorded model run, not a silent change to the criterion.

`--phase status --run-dir ...` rereads results without provider calls. Exit 0 means all declared provider cases and review gates passed; it does not claim long coding acceptance is complete. Exit 2 is input/configuration/I/O failure. Reusing an existing directory for a new collect run is rejected so old evidence cannot be overwritten by a later attempt. Failures are saved as `error.json` without deleting previous receipts.

## Reporting

Report provider model/style, selected source identities, actual successes/failures, usage and review provenance. Keep model assessments separate from code facts. The overall report always states `natural_coding_samples:0`. Sanitized sharing should omit the private database, absolute roots, credential source and any private content found during operator review; retain safe aliases, hashes, actual evidence IDs and error codes. Root must perform the separate long coding experiment before making effectiveness claims about real agent work.
