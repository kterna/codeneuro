"""Behavioral contracts for autonomous memory, evidence and reviewed mutations."""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from codeneuro.database import Conflict, DomainError
from codeneuro.governance import GovernanceService
from codeneuro.models import AgentIssue, Lifecycle, Priority, Project, Rule, RuleStatus, Task, TaskStatus
from codeneuro.service import ContextService
from codeneuro.storage import Storage


class Semantic:
    def __init__(self, decision='allow', violations=None):
        self.decision, self.violations = decision, violations or []
        self.storage = None

    def semantic_assess(self, project_id, **kwargs):
        if self.storage:
            assert self.storage._depth == 0, 'Provider inference must not hold DB transactions'
        return {'decision': self.decision, 'violations': self.violations, 'limitations': [],
                'rules_checked': [{'rule_id': r.id, 'rule_version': r.version} for r in kwargs['rules']],
                'reasoning': 'Test provider response'}

    def enqueue(self, **kwargs):
        if self.storage:
            assert self.storage._depth == 0
        return {'id': 'job_' + kwargs['request_id']}


@pytest.fixture
def env(tmp_path):
    storage = Storage(str(tmp_path / 'governance.db'))
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    storage.create_project(Project(id='p', name='project', root_paths=[str(a), str(b)]))
    storage.create_project(Project(id='q', name='other', root_paths=[str(b)]))
    storage.create_task(Task(id='task', project_id='p', title='feature', status=TaskStatus.TESTING))
    storage.create_task(Task(id='other', project_id='p', title='unrelated'))
    storage.create_task(Task(id='foreign', project_id='q', title='other project'))
    context = ContextService(storage)
    session = context.start_session('p', str(a), 'task', debug=True)['id']
    second = context.start_session('p', str(b), 'other', debug=True)['id']
    model = Semantic(); model.storage = storage
    governance = GovernanceService(storage, context, model)
    yield storage, context, governance, session, second
    storage.close()


def record(gov, session, request, exit_code=0, **kw):
    stamp = datetime.utcnow().isoformat()
    return gov.record_test_run(session_id=session, request_id=request, command=['pytest', 'tests/test_unit.py'],
        exit_code=exit_code, started_at=stamp, finished_at=stamp, paths=kw.pop('paths', ['src/unit.py']), **kw)


def candidate(gov, session, **kw):
    return gov.create_rule(session_id=session, title='Handle edge cases', content_points=['Reject empty values'],
                           scope_patterns=['src/**'], reason='Observed while implementing task', **kw)


def activate(gov, session):
    first, second = record(gov, session, 'pass-1'), record(gov, session, 'pass-2')
    return candidate(gov, session, activate=True, evidence_ids=[first['id'], second['id']])


def test_agent_activation_requires_distinct_passing_evidence_and_returns_to_observing_on_edit(env):
    store, ctx, gov, sid, _ = env
    r = candidate(gov, sid)['rule']
    assert not ctx.resolve(session_id=sid, file_path='src/unit.py').short_term_rules
    with pytest.raises(Conflict):
        gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=1, action='activate', reason='a guess')
    for index in range(2):
        evidence = record(gov, sid, f'run-{index}')
        gov.observe_rule(session_id=sid, rule_id=r['id'], expected_version=1, test_run_id=evidence['id'], supports=True, reason='tests cover empty value')
    activated = gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=1, action='activate', reason='two successful checks')
    assert activated['rule']['status'] == 'active'
    assert activated['governance']['support_count'] == 2
    assert r['id'] in [v.id for v in ctx.resolve(session_id=sid, file_path='src/unit.py').short_term_rules]
    updated = gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=2, action='update',
                              content_points=['Reject empty and whitespace values'], reason='New boundary case')
    assert updated['rule']['status'] == 'draft'
    assert updated['governance']['support_count'] == 0
    assert not ctx.resolve(session_id=sid, file_path='src/unit.py').short_term_rules
    with pytest.raises(Conflict):
        gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=2, action='revoke', reason='stale client')
    assert all(v.change_summary for v in store.list_rule_versions(r['id']))


def test_priority_reduction_keeps_valid_evidence_and_task_isolation(env):
    store, _, gov, sid, second = env
    r = activate(gov, sid)['rule']
    reduced = gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=r['version'],
                              action='reduce_priority', priority='P2', reason='Advisory after tests')
    assert reduced['rule']['status'] == 'active'
    assert reduced['governance']['support_count'] == 2
    with pytest.raises(DomainError):
        gov.mutate_rule(session_id=second, rule_id=r['id'], expected_version=reduced['rule']['version'], action='revoke', reason='wrong task')
    with pytest.raises(DomainError):
        gov.mutate_rule(session_id=sid, rule_id=r['id'], expected_version=reduced['rule']['version'], action='reduce_priority', priority='P0', reason='escalate')
    rule = store.get_rule(r['id'])
    assert rule.priority == Priority.P2


def test_evidence_cannot_be_forged_by_retries_foreign_scope_or_failed_outcomes(env):
    _, _, gov, sid, second = env
    r = candidate(gov, sid)['rule']
    stamp = datetime.utcnow().isoformat()
    data = dict(session_id=sid, command=['pytest'], exit_code=0, stdout='1 passed', started_at=stamp, finished_at=stamp, paths=['src/x.py'])
    a = gov.record_test_run(request_id='original', **data)
    b = gov.record_test_run(request_id='renamed-duplicate', **data)
    assert a['id'] == b['id']
    with pytest.raises(Conflict):
        gov.record_test_run(request_id='original', **{**data, 'stdout': '2 passed'})
    failed = record(gov, sid, 'failure', 1)
    unrelated = record(gov, sid, 'outside-scope', paths=['docs/readme.md'])
    foreign = record(gov, second, 'foreign')
    for evidence in [failed, unrelated, foreign]:
        with pytest.raises(DomainError):
            gov.observe_rule(session_id=sid, rule_id=r['id'], expected_version=1, test_run_id=evidence['id'], supports=True, reason='unsupported')


def test_pause_resume_preserves_testing_state_and_rule_versions(env):
    store, ctx, gov, sid, _ = env
    r = activate(gov, sid)['rule']
    gov.pause_task('task', 'Need review')
    assert store.get_task('task').status == TaskStatus.PAUSED
    assert not ctx.resolve(session_id=sid, file_path='src/a.py').short_term_rules
    with pytest.raises(DomainError):
        candidate(gov, sid)
    with pytest.raises(Conflict):
        store.update_task_status('task', TaskStatus.ACTIVE)
    gov.resume_task('task', 'Review complete')
    assert store.get_task('task').status == TaskStatus.TESTING
    assert store.get_rule(r['id']).version == r['version']
    assert ctx.resolve(session_id=sid, file_path='src/a.py').short_term_rules


def test_real_failed_commands_recovery_and_root_cause_are_retrievable(env):
    store, ctx, gov, sid, _ = env
    # Execute real isolated processes, preserving their actual results as evidence.
    command = [sys.executable, '-c', 'import os; assert os.environ.get("CASE_FIXED") == "1", "missing fix"']
    import os
    for index in range(3):
        start = datetime.utcnow().isoformat()
        result = subprocess.run(command, capture_output=True, text=True, env={**os.environ, 'CASE_FIXED': str(int(index == 2))})
        gov.record_test_run(session_id=sid, request_id=f'actual-{index}', command=command,
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
            started_at=start, finished_at=datetime.utcnow().isoformat(), paths=['src/unit.py'])
    reflection = gov.overview('p')['reflections'][0]
    assert reflection['status'] == 'recovered'
    assert len(reflection['failure_run_ids']) == 2
    assert reflection['finding_id']
    gov.explain_reflection(session_id=sid, reflection_id=reflection['id'], analysis='The subprocess lacked the required CASE_FIXED environment flag.')
    rendered = ctx.resolve(session_id=sid, file_path='src/unit.py').rendered_markdown
    assert reflection['recovery_run_id'] in rendered
    assert 'CASE_FIXED' in rendered
    assert 'does not establish the root cause' in rendered
    runs = gov.overview('p')['test_runs']
    assert {r['source'] for r in runs} == {'client_reported'}
    assert sorted(r['exit_code'] for r in runs) == [0, 1, 1]


def test_cleanup_retires_unvalidated_keeps_validated_and_queues_durable_distillation(env):
    store, _, gov, sid, _ = env
    valid = activate(gov, sid)['rule']
    unvalidated = candidate(gov, sid)['rule']
    result = gov.cleanup_session(sid, 'finish')
    assert valid['id'] in result['retained_rule_ids']
    assert unvalidated['id'] in result['revoked_rule_ids']
    assert gov.cleanup_session(sid, 'retry')['duplicate']
    assert len(gov.overview('p')['distillation_requests']) == 1
    assert store.get_rule(unvalidated['id']).status == RuleStatus.REVOKED
    outcomes = gov.process_pending_distillations()
    assert outcomes[0]['status'] == 'queued'
    assert not gov.process_pending_distillations()
    assert store.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert list(store.conn.execute('PRAGMA foreign_key_check')) == []


def test_task_release_expires_rules_and_durably_triggers_distillation(env):
    store, ctx, gov, sid, _ = env
    valid = activate(gov, sid)['rule']
    store.update_task_status('task', TaskStatus.RELEASED)
    assert store.get_rule(valid['id']).status == RuleStatus.DEPRECATED
    assert not ctx.resolve(session_id=sid, file_path='src/unit.py').short_term_rules
    requests = gov.overview('p')['distillation_requests']
    assert requests[0]['source'] == 'task_completion'
    another = Storage(store.db_path)
    assert GovernanceService(another).overview('p')['distillation_requests'][0]['id'] == requests[0]['id']
    another.close()


def test_aging_is_explicit_and_never_silently_removes_p0(env):
    store, ctx, gov, sid, _ = env
    evidence = [record(gov, sid, 'run-1')['id'], record(gov, sid, 'run-2')['id']]
    r = candidate(gov, sid, activate=True, evidence_ids=evidence, priority='P0', half_life_days=1)['rule']
    store.conn.execute('UPDATE governance_observations SET created_at=?', ((datetime.utcnow() - timedelta(days=3)).isoformat(),))
    status = gov.overview('p')['rules'][0]
    assert status['stale'] and status['effective_confidence'] < .1
    assert ctx.resolve(session_id=sid, file_path='src/unit.py').short_term_rules[0].id == r['id']


def test_reviewed_proposal_merge_keeps_source_versions_and_conflicts(env):
    store, _, gov, sid, _ = env
    source = activate(gov, sid)['rule']
    target = store.create_rule(Rule(id='contract', project_id='p', title='Interface contract', lifecycle=Lifecycle.LONG_TERM,
                                   content_points=['Preserve calls'], scope_patterns=['src/**']))
    change = {'action': 'merge', 'rule_id': target.id, 'expected_version': 1,
              'content_points': ['Preserve calls', 'Reject empty values'], 'source_rule_ids': [source['id']]}
    proposal = gov.propose_change('p', change=change, task_id='task', reason='Useful beyond this feature')
    assert proposal['source_refs'] == [{'kind': 'rule', 'id': source['id'], 'version': source['version']}]
    with pytest.raises(DomainError):
        gov.apply_proposal(proposal['id'], reviewed=False, reason='not reviewed')
    result = gov.apply_proposal(proposal['id'], reviewed=True, reason='Inspected source and exact new contract')
    assert result['rule']['id'] == target.id and result['rule']['version'] == 2
    assert len(store.list_rule_versions(target.id)) == 2
    assert gov.apply_proposal(proposal['id'], reviewed=True, reason='retry')['duplicate']
    with pytest.raises(Conflict):
        gov.propose_change('p', change=change, reason='old target version')


def test_issue_apply_is_atomic_and_does_not_execute_suggestion_text(env):
    store, _, gov, _, _ = env
    rule = store.create_rule(Rule(id='r', project_id='p', title='Old', lifecycle=Lifecycle.LONG_TERM,
                                 content_points=['old'], scope_patterns=['src/**']))
    issue = store.record_issue(AgentIssue(id='issue', project_id='p', title='Outdated', description='Old text',
                                         file_path='src/unit.py', related_rule_ids=[rule.id], suggested_action='rm -rf /'))
    change = {'action': 'update', 'rule_id': rule.id, 'expected_version': 1, 'content_points': ['new instruction']}
    store.conn.execute("CREATE TRIGGER fail_governance_version BEFORE INSERT ON rule_versions WHEN NEW.version_number=2 BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        gov.apply_issue_suggestion(issue.id, reviewed=True, change=change, reason='Reviewed')
    assert store.list_issues('p')[0].status.value == 'open'
    assert not gov.overview('p')['proposals']
    assert store.get_rule(rule.id).version == 1
    store.conn.execute('DROP TRIGGER fail_governance_version')
    result = gov.apply_issue_suggestion(issue.id, reviewed=True, change=change, reason='Reviewed')
    assert result['issue_status'] == 'resolved'
    assert result['rule']['content_points'] == ['new instruction']


def test_preflight_blocks_grounded_semantic_p0_allows_valid_and_downgrades_unfounded(env):
    store, _, gov, sid, _ = env
    store.create_rule(Rule(id='p0', project_id='p', title='No deletion', lifecycle=Lifecycle.LONG_TERM, priority=Priority.P0,
                          content_points=['Retain compatibility API'], scope_patterns=['src/**']))
    gov.intelligence = Semantic('block', [{'rule_id': 'p0', 'rule_version': 1, 'severity': 'violation',
        'reason': 'The plan deletes the API required by the contract', 'evidence': [{'path': 'src/unit.py', 'line': 1}],
        'plan_excerpt': 'Delete the compatibility API'}])
    blocked = gov.preflight(session_id=sid, request_id='bad', files=['src/unit.py'], plan='Delete the compatibility API')
    assert blocked['decision'] == 'block'
    gov.intelligence = Semantic()
    allowed = gov.preflight(session_id=sid, request_id='good', files=['src/unit.py'], plan='Add an internal adapter while retaining the public API')
    assert allowed['decision'] == 'allow'
    gov.intelligence = Semantic('block', [{'rule_id': 'p0', 'rule_version': 1, 'severity': 'violation', 'reason': 'guess'}])
    assert gov.preflight(session_id=sid, request_id='guess', files=['src/unit.py'], plan='Add documentation')['decision'] == 'review'


def test_preflight_replays_become_review_when_rules_change_and_provider_fails_closed(env):
    store, _, gov, sid, _ = env
    store.create_rule(Rule(id='r', project_id='p', title='Constraint', lifecycle=Lifecycle.LONG_TERM, content_points=['x'], scope_patterns=['src/**']))
    req = dict(session_id=sid, request_id='before', files=['src/unit.py'], plan='Modify implementation')
    assert gov.preflight(**req)['decision'] == 'allow'
    store.update_rule_content('r', 'Constraint', ['y'], ['src/**'], Priority.P0, expected_version=1)
    stale = gov.preflight(**req)
    assert stale['stale'] and stale['decision'] == 'review'
    class Down:
        def semantic_assess(self, *a, **kw):
            raise DomainError('Service unavailable', 'provider_unavailable')
    gov.intelligence = Down()
    assert gov.preflight(**{**req, 'request_id': 'outage'})['decision'] == 'review'


def test_explicit_policy_checks_real_added_lines_and_versions(env):
    store, _, gov, sid, _ = env
    store.create_rule(Rule(id='p0', project_id='p', title='No direct evaluation', lifecycle=Lifecycle.LONG_TERM, priority=Priority.P0,
                          content_points=['Do not add direct eval calls'], scope_patterns=['src/**']))
    gov.set_policy('p0', expected_version=1, reviewed=True, spec={'kind': 'forbid_added_literal', 'literal': 'eval('})
    bad = '--- a/src/unit.py\n+++ b/src/unit.py\n@@ -1 +1 @@\n-old\n+eval(request)\n'
    result = gov.preflight(session_id=sid, request_id='literal', files=['src/unit.py'], plan='Handle request', diff=bad)
    assert result['decision'] == 'block'
    assert result['checks'][0]['evidence'][0]['line'] == 1
    good = bad.replace('+eval(request)', '+parse(request)')
    assert gov.preflight(session_id=sid, request_id='good-literal', files=['src/unit.py'], plan='Handle request', diff=good)['decision'] == 'allow'
    assert gov.preflight(session_id=sid, request_id='missing-diff', files=['src/unit.py'], plan='Handle request')['decision'] == 'review'


def test_concurrent_proposal_review_applies_once(env):
    store, _, gov, _, _ = env
    proposal = gov.propose_change('p', change={'action': 'create', 'title': 'Permanent', 'content_points': ['Follow interface'],
                                              'scope_patterns': ['src/**']}, reason='review required')
    other = Storage(store.db_path)
    def apply(service):
        return service.apply_proposal(proposal['id'], reviewed=True, reason='Reviewed')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(apply, [gov, GovernanceService(other)]))
    assert results[0]['rule']['id'] == results[1]['rule']['id']
    assert sum(r['duplicate'] for r in results) == 1
    other.close()


def test_manual_content_edit_invalidates_agent_evidence_and_old_runs_cannot_revalidate(env):
    store, _, gov, sid, _ = env
    result = activate(gov, sid)
    r = result['rule']
    evidence = result['governance']['observations'][0]['test_run_id']
    updated = store.update_rule_content(r['id'], r['title'], ['Different assertion'], ['src/**'], Priority.P1,
                                        expected_version=r['version'])
    assert gov.overview('p')['rules'][0]['support_count'] == 0
    with pytest.raises(DomainError):
        gov.observe_rule(session_id=sid, rule_id=r['id'], expected_version=updated.version,
                         test_run_id=evidence, supports=True, reason='old evidence cannot validate a different claim')


def test_noop_rule_edit_and_status_change_preserve_evidence(env):
    store, _, gov, sid, _ = env
    result = activate(gov, sid)
    r = store.get_rule(result['rule']['id'])
    store.update_rule_content(r.id, r.title, r.content_points, r.scope_patterns, r.priority, expected_version=r.version)
    assert gov.overview('p')['rules'][0]['support_count'] == 2


def test_cleanup_checkpoint_then_final_close_cleans_new_drafts(env):
    store, _, gov, sid, _ = env
    first = candidate(gov, sid)['rule']
    assert gov.cleanup_session(sid, 'checkpoint', close=False)['revoked_rule_ids'] == [first['id']]
    later = candidate(gov, sid)['rule']
    result = gov.cleanup_session(sid, 'final', close=True)
    assert later['id'] in result['revoked_rule_ids'] and result['closed']
    assert store.get_rule(later['id']).status == RuleStatus.REVOKED


def test_http_contracts_pause_rule_observe_and_human_review(env):
    from fastapi.testclient import TestClient
    from codeneuro.api import create_app
    from codeneuro.governance_api import create_governance_router
    store, ctx, gov, sid, _ = env
    app = create_app(store)
    app.include_router(create_governance_router(store, ctx, gov.intelligence))
    with TestClient(app) as client:
        assert client.patch('/api/tasks/task/pause', json={'reason': 'inspection'}).json()['status'] == 'paused'
        assert client.patch('/api/tasks/task/resume', json={'reason': 'done'}).json()['status'] == 'testing'
        created = client.post('/api/agent/rules', json={'session_id': sid, 'title': 'Temporary',
            'content_points': ['Use boundary checks'], 'scope_patterns': ['src/**'], 'reason': 'task finding'})
        assert created.status_code == 200, created.text
        rule = created.json()['rule']
        assert client.patch('/api/agent/rules/' + rule['id'], json={'session_id': sid, 'expected_version': 1,
            'action': 'activate', 'reason': 'missing proof'}).status_code == 409
        proposal = client.post('/api/projects/p/governance/proposals', json={'reason': 'review this exact change',
            'change': {'action': 'create', 'title': 'Contract', 'content_points': ['Permanent guarantee'], 'scope_patterns': ['src/**']}})
        assert proposal.status_code == 200, proposal.text
        applied = client.post('/api/governance/proposals/' + proposal.json()['id'] + '/apply',
                              json={'reviewed': True, 'reason': 'Inspected', 'reviewer': 'tester'})
        assert applied.status_code == 200, applied.text
        assert applied.json()['rule']['lifecycle'] == 'long_term'
        assert client.get('/api/projects/p/governance').json()['proposals'][0]['status'] == 'applied'
        assert client.post('/api/agent/preflight', json={'session_id': sid, 'request_id': 'http',
            'files': ['src/unit.py'], 'plan': 'Retain the guarantee'}).json()['decision'] == 'allow'
