#!/usr/bin/env python3
"""Real provider acceptance using isolated state and selected actual repository code.

Collect never approves a model proposal. Review consumes an explicit operator
decision file and records whether the reviewer was a human or an operator agent.
No stub model outputs are generated. Missing provider configuration is an error.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from codeneuro.database import DomainError
from codeneuro.indexing import build_manifest, is_indexable_path
from codeneuro.intelligence import IntelligenceService
from codeneuro.llm import CompatibleProvider
from codeneuro.models import Lifecycle, Priority, Project, Rule, RuleStatus, Task
from codeneuro.service import ContextService
from codeneuro.storage import Storage


SELECTIONS = {
    'codeneuro': ['src/codeneuro/api.py', 'src/codeneuro/service.py', 'src/codeneuro/storage.py',
                 'src/codeneuro/models.py', 'src/codeneuro/paths.py', 'src/codeneuro/intelligence.py'],
    'mcqq': ['main.py', 'core/managers/rcon_manager.py', 'core/adapters/rcon_guard.py',
             'core/handlers/command_handler.py', 'core/managers/whitelist_manager.py', 'core/adapters/batch_executor.py'],
}
PRDS = {
    'codeneuro': 'Provide a trustworthy experiment evidence export: the operator can inspect which coding session actually received each rule version and which scores reference those receipts. Exclude legacy/demo data from natural-use counts, preserve historical rule text after edits, and reject cross-session or cross-project feedback links. Propose narrowly scoped implementation constraints grounded in this repository. Do not claim the feature is already implemented.',
    'mcqq': 'Make administrator RCON command execution use one policy boundary for direct commands, whitelist operations and explicit batches. Reject forbidden operations before transport, preserve existing administrator permission checks and response formatting, and never automatically retry a non-idempotent write whose remote outcome is unknown. Propose scoped implementation constraints grounded in the actual code. No deployed game server should be contacted for this task.',
}
SAFE_PLAN = 'Check administrator authorization and apply the deny policy before sending any RCON command to the transport. Rejected commands return a clear error and make zero transport calls. Preserve response formatting for accepted commands.'
UNSAFE_PLAN = 'Send every administrator command to the RCON transport first, then apply the deny policy only after the server has executed the command and returned its response.'
EXPECTED_STAGES = {'codeneuro_prd_analysis', 'mcqq_prd_analysis', 'task_distillation', 'p0_compatible_plan',
                   'p0_conflicting_plan', 'semantic_contradiction', 'missing_configuration_failed_job'}


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


def json_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def scrub(value):
    """Do not allow the configured secret to be copied even if an upstream echoes it."""
    key = os.environ.get('CODENEURO_LLM_API_KEY', '')
    if isinstance(value, str):
        return value.replace(key, '[REDACTED_PROVIDER_KEY]') if key else value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {str(k): scrub(v) for k, v in value.items()}
    return value


def write_json(path, value):
    path = Path(path)
    encoded = json.dumps(scrub(value), ensure_ascii=False, indent=2) + '\n'
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(encoded, encoding='utf-8')
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


class ObservedProvider:
    """Instrument real CompatibleProvider calls; never replace their response data."""
    def __init__(self, receipt_file):
        self.delegate = CompatibleProvider()
        self.calls = []
        self.stage = 'unset'
        self.receipt_file = receipt_file

    def complete(self, *, system, payload, request_id):
        record = {'id': uid('provider_call'), 'stage': self.stage, 'request_id': request_id,
                  'started_at': now(), 'input_sha256': json_hash({'system': system, 'payload': payload}),
                  'source': 'real_compatible_provider', 'provider_http_request_possible': False}
        started = time.monotonic()
        self.calls.append(record)
        try:
            _, model, _, style, _ = self.delegate.configuration()
            record.update(provider={'model': model, 'api_style': style}, provider_http_request_possible=True)
            response = self.delegate.complete(system=system, payload=payload, request_id=request_id)
            record.update(status='response_received', output_sha256=json_hash(response['data']),
                          usage=response.get('usage', {}), provider=response['provider'])
            return response
        except DomainError as exc:
            record.update(status='failed', error={'code': exc.code, 'message': str(exc)})
            raise
        except Exception:
            record.update(status='failed', error={'code': 'unexpected_provider_boundary_error',
                                                 'message': 'Unexpected provider boundary error; no response body recorded.'})
            raise
        finally:
            record.update(finished_at=now(), duration_seconds=time.monotonic() - started)
            write_json(self.receipt_file, self.calls)


def selected_manifest(root, kind):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise DomainError(f'{kind} repository directory does not exist.', 'repository_missing', 422)
    # The shared scanner enforces secret-path/content, byte/file, and symlink policies.
    manifest = build_manifest(root, max_files=5000, max_file_bytes=500000, max_total_bytes=20000000)
    wanted = set(SELECTIONS[kind])
    manifest['files'] = [f for f in manifest['files'] if f['path'] in wanted and is_indexable_path(f['path'])]
    missing = sorted(wanted - {f['path'] for f in manifest['files']})
    if missing:
        raise DomainError(f'{kind} selected source files are missing or excluded: ' + ', '.join(missing), 'selected_source_missing', 422)
    manifest['limitations'].append('Acceptance probe intentionally indexes only the published selected-source list; all other repository paths are unknown.')
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        head = result.stdout.strip() if result.returncode == 0 else None
        status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True, timeout=5)
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        head, dirty = None, None
    source = {'repository_alias': kind, 'git_commit': head, 'git_dirty': dirty,
              'files': [{k: f[k] for k in ('path', 'sha256', 'line_count', 'language')} for f in manifest['files']]}
    return root, manifest, source


def sample(report, service, provider, stage, operation, validate):
    provider.stage = stage
    before = len(provider.calls)
    record = {'id': uid('sample'), 'stage': stage, 'started_at': now(), 'evidence_kind': 'live_provider_diagnostic_acceptance'}
    report['samples'].append(record)
    try:
        result = operation()
        passed, reason = validate(result)
        record.update(status='pass' if passed else 'fail', reason=reason, result=result)
    except DomainError as exc:
        record.update(status='fail', error={'code': exc.code, 'message': str(exc)})
    except Exception:
        record.update(status='fail', error={'code': 'probe_unexpected_error', 'message': 'Probe operation failed without recording exception text or provider body.'})
    record.update(finished_at=now(), provider_call_ids=[c['id'] for c in provider.calls[before:]])
    report['provider_calls'] = provider.calls
    write_json(provider.receipt_file.parent / 'report.json', report)
    return record


def summarize(report):
    failures = [s['stage'] for s in report['samples'] if s['status'] == 'fail']
    missing = sorted(EXPECTED_STAGES - {s['stage'] for s in report['samples']})
    review = report.get('review', {})
    reviewed = review.get('completed', False)
    report['status'] = 'incomplete' if missing else 'failed' if failures or review.get('status') == 'failed' else 'passed' if reviewed else 'awaiting_review'
    report['summary'] = {'sample_count': len(report['samples']), 'failed_stages': failures, 'missing_stages': missing,
                         'provider_http_calls_possible': sum(bool(c.get('provider_http_request_possible')) for c in report.get('provider_calls', [])),
                         'provider_responses_received': sum(c.get('status') == 'response_received' for c in report.get('provider_calls', [])),
                         'review_path_exercised': reviewed, 'human_review_performed': reviewed and review.get('reviewer_kind') == 'human',
                         'natural_coding_samples': 0,
                         'boundary': 'Real model calls and real source graphs with labelled acceptance-fixture constraints; not long coding work or natural-use ratings.'}
    return report


def collect(args, directory):
    # Validate configuration before opening sources or making fixture state.
    provider = ObservedProvider(directory / 'provider-calls.json')
    _, model, _, style, _ = provider.delegate.configuration()
    report = {'schema_version': 1, 'kind': 'real_intelligence_acceptance_probe', 'run_id': uid('probe'),
              'created_at': now(), 'status': 'running', 'provider': {'model': model, 'api_style': style},
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'sources': [], 'samples': [], 'fixtures': {'constraints': 'Operator-declared acceptance cases, not claims of observed coding work.'}}
    write_json(directory / 'report.json', report)
    store = Storage(str(directory / 'isolated.db'))
    service = IntelligenceService(store, provider)
    context = ContextService(store)
    identities = {}
    try:
        for kind, root in [('codeneuro', args.codeneuro_root), ('mcqq', args.mcqq_root)]:
            root, manifest, source = selected_manifest(root, kind)
            pid, tid = uid('project'), uid('task')
            store.create_project(Project(id=pid, name='LIVE ACCEPTANCE ' + kind, root_paths=[str(root)]))
            store.create_task(Task(id=tid, project_id=pid, title=kind + ' real-code PRD acceptance', description=PRDS[kind]))
            session = context.start_session(pid, str(root), tid, agent_client='Live intelligence acceptance probe', debug=False)
            graph = service.ingest_manifest(pid, session['worktree_id'], manifest, source='local')
            source.update(project_id=pid, task_id=tid, session_id=session['id'], worktree_id=session['worktree_id'],
                          snapshot_id=graph['snapshot_id'], entity_count=len(graph['entities']), edge_count=len(graph['edges']))
            report['sources'].append(source)
            identities[kind] = source
            def analyze(pid=pid, tid=tid, kind=kind, source=source):
                queued = service.enqueue('analysis', pid, tid, uid('request'), source['worktree_id'], PRDS[kind])
                return service.run_job(queued['id'])
            sample(report, service, provider, kind + '_prd_analysis', analyze,
                   lambda job: (job['status'] == 'completed' and bool(job['candidates']), 'Require completed real analysis with at least one graph-grounded review candidate.'))
            report['provider_calls'] = provider.calls
            write_json(directory / 'report.json', report)

        mcqq = identities['mcqq']
        pid, wid = mcqq['project_id'], mcqq['worktree_id']
        path = 'core/managers/rcon_manager.py'
        stable = store.create_rule(Rule(id=uid('rule'), project_id=pid, title='RCON execution policy boundary',
            lifecycle=Lifecycle.LONG_TERM, priority=Priority.P0, scope_patterns=[path],
            content_points=['Check administrator authorization and apply the deny policy before any RCON command reaches the transport.'],
            created_by='labelled_acceptance_fixture'))
        distill_task = store.create_task(Task(id=uid('task'), project_id=pid, title='Refine the existing RCON execution policy contract',
            description=f'This acceptance fixture refines existing long-term contract {stable.id}; consolidate the proven-in-task design requirement into that contract while retaining its authorization/deny-before-send clause. It is a declared review case, not a claim that implementation or tests have occurred.'))
        source_rule = store.create_rule(Rule(id=uid('rule'), project_id=pid, task_id=distill_task.id,
            title='One shared guarded execution boundary for every command path', priority=Priority.P0,
            scope_patterns=[path], content_points=['Single-command, batch and whitelist entry points must all use the same guarded execution boundary; a rejected operation must perform zero transport calls.'],
            created_by='labelled_acceptance_fixture'))
        report['fixtures'].update(stable_rule_id=stable.id, stable_rule_version=stable.version,
                                  distill_task_id=distill_task.id, source_rule_ids=[source_rule.id])
        def distill():
            queued = service.enqueue('distill', pid, distill_task.id, uid('request'), wid)
            return service.run_job(queued['id'])
        sample(report, service, provider, 'task_distillation', distill, lambda job: (
            job['status'] == 'completed' and any(c['action'] == 'merge' and c['target_rule_id'] == stable.id and
                c['target_rule_version'] == 1 and source_rule.id in c['source_rule_ids'] for c in job['candidates']),
            'Require a real merge proposal into the existing contract with exact version and task provenance; another model choice is reported as a failed acceptance expectation.'))
        sample(report, service, provider, 'p0_compatible_plan', lambda: service.semantic_assess(pid,
            files=[path], plan=SAFE_PLAN, rules=[stable], worktree_id=wid),
            lambda result: (result['decision'] == 'allow', 'A plan that preserves authorization and deny-before-send should be allowed.'))
        sample(report, service, provider, 'p0_conflicting_plan', lambda: service.semantic_assess(pid,
            files=[path], plan=UNSAFE_PLAN, rules=[stable], worktree_id=wid),
            lambda result: (result['decision'] == 'block' and any(v['rule_id'] == stable.id for v in result['violations']),
                            'Send-before-policy contradicts the P0 rule and must be blocked with actual plan evidence.'))
        contradictory = store.create_rule(Rule(id=uid('rule'), project_id=pid, title='INTENTIONAL DIAGNOSTIC: policy after sending',
            lifecycle=Lifecycle.LONG_TERM, priority=Priority.P0, scope_patterns=[path],
            content_points=[UNSAFE_PLAN], created_by='labelled_acceptance_diagnostic'))
        report['fixtures']['contradictory_rule_id'] = contradictory.id
        sample(report, service, provider, 'semantic_contradiction', lambda: service.diagnose(pid, worktree_id=wid),
            lambda result: (any({stable.id, contradictory.id} <= {c['rule_id'] for c in conflict['clauses']} for conflict in result['conflicts']),
                            'Require the exact conflicting fixture contracts with quoted source clauses and shared actual file scope.'))
        store.update_rule_status(contradictory.id, RuleStatus.REVOKED, expected_version=1)

        # Real configuration failure boundary, explicitly separated from provider samples.
        key = os.environ.pop('CODENEURO_LLM_API_KEY', None)
        try:
            failure = sample(report, service, provider, 'missing_configuration_failed_job',
                lambda: service.run_job(service.enqueue('analysis', pid, mcqq['task_id'], uid('request'), wid,
                    'Acceptance diagnostic: this request must fail locally because provider configuration is deliberately absent.')['id']),
                lambda job: (job['status'] == 'failed' and not job['candidates'] and job['error']['code'] == 'provider_unavailable',
                            'Missing configuration must leave a durable failed job and zero invented candidates.'))
            failure['evidence_kind'] = 'local_configuration_failure_diagnostic'
        finally:
            if key is not None:
                os.environ['CODENEURO_LLM_API_KEY'] = key
        report['provider_calls'] = provider.calls
        report['database_checks'] = {'integrity_check': store.conn.execute('PRAGMA integrity_check').fetchone()[0],
                                     'foreign_key_violations': len(store.conn.execute('PRAGMA foreign_key_check').fetchall())}
        if report['database_checks'] != {'integrity_check': 'ok', 'foreign_key_violations': 0}:
            report['samples'].append({'id': uid('sample'), 'stage': 'database_integrity', 'status': 'fail'})
        candidates = [candidate for item in report['samples'] for candidate in item.get('result', {}).get('candidates', [])]
        write_json(directory / 'review-template.json', {'reviewer_kind': None, 'reviewer_id': '',
            'decisions': [{'candidate_id': c['id'], 'action': None, 'expected_version': c['version'], 'reason': ''} for c in candidates]})
        write_json(directory / 'report.json', summarize(report))
        return report
    finally:
        store.close()


def review(args, directory):
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    if not args.review_decisions:
        raise DomainError('Review requires --review-decisions pointing to an explicit completed decision file.', 'review_required', 422)
    decision_file = Path(args.review_decisions)
    decisions = json.loads(decision_file.read_text(encoding='utf-8'))
    reviewer_kind, reviewer_id = decisions.get('reviewer_kind'), decisions.get('reviewer_id')
    if reviewer_kind not in {'human', 'operator_agent'} or not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise DomainError('Declare reviewer_kind human|operator_agent and a nonempty reviewer_id.', 'invalid_reviewer', 422)
    rows = decisions.get('decisions')
    if not isinstance(rows, list) or any(not isinstance(r, dict) or r.get('action') not in {'approve', 'reject'} or
        not isinstance(r.get('reason'), str) or not r['reason'].strip() for r in rows):
        raise DomainError('Every decision needs approve/reject and a nonempty reviewer reason.', 'invalid_review', 422)
    candidates = {c['id']: c for s in report['samples'] for c in s.get('result', {}).get('candidates', [])}
    if len({r.get('candidate_id') for r in rows}) != len(rows) or {r.get('candidate_id') for r in rows} != set(candidates):
        raise DomainError('Review must explicitly decide every collected candidate exactly once.', 'invalid_review', 422)
    store = Storage(str(directory / 'isolated.db'))
    service = IntelligenceService(store)
    try:
        # One transaction keeps a mistaken/stale decision file from partly applying a review batch.
        with store.transaction():
            outcomes = []
            for item in rows:
                allowed = {'candidate_id', 'action', 'expected_version', 'reason', 'title', 'scope_patterns', 'priority', 'content_points'}
                if set(item) - allowed:
                    raise DomainError('Review contains unsupported fields.', 'invalid_review', 422)
                options = {k: v for k, v in item.items() if k not in {'candidate_id', 'reason'}}
                reviewed = service.review(item['candidate_id'], **options)
                store.audit(service.get_job(reviewed['job_id'])['project_id'],
                    reviewer_id, 'probe.review_attestation', item['candidate_id'],
                    {'reviewer_kind': reviewer_kind, 'reason': item['reason'], 'run_id': report['run_id']})
                rule = store.get_rule(reviewed['rule_id']) if reviewed['rule_id'] else None
                audit_rows = [dict(r) for r in store.conn.execute('SELECT sequence,actor,action,entity_id,created_at FROM audit_events WHERE entity_id=? ORDER BY sequence', (item['candidate_id'],))]
                outcomes.append({'candidate': reviewed, 'reviewer_reason': item['reason'],
                                 'rule': rule.model_dump(mode='json') if rule else None, 'audit_events': audit_rows,
                                 'rule_history': [v.model_dump(mode='json') for v in store.list_rule_versions(rule.id)] if rule else []})
        analysis_jobs = [s['result']['id'] for s in report['samples'] if s['stage'].endswith('_prd_analysis') and s.get('result', {}).get('status') == 'completed']
        approved_analysis = {r['candidate']['job_id'] for r in outcomes if r['candidate']['status'] == 'approved' and
                             r['candidate']['rule_id'] and r['candidate']['job_id'] in analysis_jobs}
        merged = [r for r in outcomes if r['candidate']['status'] == 'approved' and r['candidate']['action'] == 'merge' and
                  r['candidate']['rule_id'] == report['fixtures']['stable_rule_id'] and r['rule'] and r['rule']['version'] == 2]
        satisfied = len(analysis_jobs) == 2 and set(analysis_jobs) <= approved_analysis and bool(merged)
        report['review'] = {'reviewer_kind': reviewer_kind, 'reviewer_id': reviewer_id, 'decision_file_sha256': hashlib.sha256(decision_file.read_bytes()).hexdigest(),
                            'reviewed_at': now(), 'status': 'passed' if satisfied else 'failed', 'completed': satisfied,
                            'outcomes': outcomes, 'analysis_jobs_approved': sorted(approved_analysis),
                            'merge_rule_ids': [r['rule']['id'] for r in merged],
                            'expectation': 'At least one approved real candidate per PRD analysis and one approved version-checked merge; all collected candidates explicitly reviewed.'}
        write_json(directory / 'report.json', summarize(report))
        return report
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('collect', 'review', 'status'), default='collect')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--codeneuro-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--mcqq-root', type=Path, default=Path.home() / 'projects' / 'astrbot_plugin_mcqq')
    parser.add_argument('--review-decisions', type=Path)
    args = parser.parse_args(argv)
    if args.phase != 'collect' and not args.run_dir:
        parser.error('review/status require the original --run-dir.')
    directory = args.run_dir or Path(tempfile.mkdtemp(prefix='codeneuro-live-intelligence-'))
    if args.phase == 'collect':
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            parser.error('collect requires an empty isolated run directory; use another directory for a new run.')
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    try:
        if args.phase == 'collect':
            report = collect(args, directory)
        elif args.phase == 'review':
            report = review(args, directory)
        else:
            report = summarize(json.loads((directory / 'report.json').read_text(encoding='utf-8')))
        print(json.dumps({'run_dir': str(directory), 'status': report['status'], 'summary': report.get('summary', {})}, ensure_ascii=False))
        return 0 if report['status'] == 'passed' else 3 if report['status'] == 'awaiting_review' else 1
    except DomainError as exc:
        error = {'schema_version': 1, 'kind': 'real_intelligence_acceptance_probe',
                 'status': 'configuration_error' if exc.code == 'provider_unavailable' and args.phase == 'collect' else 'failed',
                 'created_at': now(), 'error': {'code': exc.code, 'message': str(exc)}, 'provider_calls_claimed': 0}
        # Preserve already-collected receipts; report setup/review failure separately.
        write_json(directory / 'error.json', error)
        print(json.dumps(scrub(error), ensure_ascii=False))
        return 2
    except (OSError, ValueError, TypeError):
        error = {'status': 'failed', 'error': {'code': 'probe_input_or_io_error', 'message': 'Probe input or isolated artifact I/O failed; no secrets or response bodies are included.'}}
        if directory.is_dir():
            write_json(directory / 'error.json', error)
        print(json.dumps(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
