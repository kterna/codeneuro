"""Core context, governance, evidence and lifecycle regressions for direct Task scope."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.knowledge import Priority, matches
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from helpers import initialize_database, configure_fixture, create_scope, file_query, propose_review


@pytest.fixture
def app(tmp_path):
    filename = str(tmp_path / 'product.db')
    initialize_database(filename)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    for project in ('p', 'q'):
        product.workspaces.register_project(human, project, project)
    configure_fixture(product, human, ('p', 'q'))
    parent, task = create_scope(product, agent)
    yield product, uow, human, agent, task, parent, filename
    uow.dispose()


def update(product, agent, task, **changes):
    return product.workspaces.manage_task(agent, 'p', 'update', task.id, task.version, changes, 'Explicit progress')


def finish(product, agent, task):
    return update(product, agent, update(product, agent, task, status='testing'),
                  status='completed', verification_summary='Manual scenarios passed')


def test_scope_feedback_and_selected_p0_survive_budget(app):
    p, _, human, agent, task, *_ = app
    p0 = p.knowledge.create_rule(human, 'p', 'Guard', ('CRITICAL' * 160,), ('src/**',), Priority.P0)
    p1 = p.knowledge.create_rule(human, 'p', 'Business', ('Needed',), ('src/**',))
    other = p.knowledge.create_rule(human, 'p', 'Other folder', ('Not here',), ('tests/**',))
    query = file_query(('src/main.py',), priorities=(Priority.P0,), max_chars=512)
    delivered = p.context.get_context(agent, 'p', query, 'budgeted', task_id=task.id)
    assert delivered.budget_exceeded and 'CRITICAL' * 160 in delivered.markdown
    assert [ref[0] for ref in delivered.rule_refs] == [p0.id] and other.id not in delivered.markdown
    full = p.context.get_context(agent, 'p', file_query(('src/main.py',)), 'full', task_id=task.id)
    assert p.feedback.rate_rule(agent, full.id, p1.id, 0)['duplicate'] is False
    assert p.feedback.rate_rule(agent, full.id, p1.id, 0)['duplicate'] is True
    again = p.context.get_context(Actor('other-agent'), 'p', file_query(('src/main.py',)), task_id=task.id)
    assert (p1.id, 1, 'full') in again.rule_refs and (p0.id, 1, 'full') in again.rule_refs
    assert matches('src/**', 'src/main.py') and not matches('src/*.py', 'src/deep/main.py')


def test_scope_density_counts_actual_rules_without_invented_files(app):
    p, _, human, _, task, *_ = app
    p.knowledge.create_rule(human, 'p', 'Architecture', ('Invariant',), ('src/**',), Priority.P0)
    p.knowledge.create_rule(human, 'p', 'Task', ('Work',), ('src/pay/**',), task_id=task.id)
    scopes = p.ledger.project(human, 'p')['scope_density']
    assert [scope['scope'] for scope in scopes] == ['src', 'src/pay']
    assert scopes[0]['p0'] == 1 and scopes[1]['short_term'] == 1 and scopes[1]['rule_ids']
    assert all('files' not in scope for scope in scopes)


def test_conflict_advisory_uses_exact_current_delivered_versions(app):
    p, uow, human, agent, task, *_ = app
    left = p.knowledge.create_rule(human, 'p', 'Signed payload', ('Always sign',), ('src/**',), Priority.P0)
    right = p.knowledge.create_rule(human, 'p', 'Task instruction', ('Check auth',), ('src/**',), task_id=task.id)
    issue = p.feedback.report_issue(agent, 'p', 'conflict', 'Potential conflict', 'Agent observation',
                                    'src/api.py', (left.id, right.id), task_id=task.id)
    query = file_query(('src/api.py',))
    result = p.context.get_context(agent, 'p', query, 'conflict-1', task_id=task.id)
    assert result.conflict_assessment == 'not_assessed' and issue.id in result.markdown
    assert result.reported_conflicts[0]['rule_refs'] == ((left.id, 1), (right.id, 1))
    with uow.write() as tx:
        tx.knowledge.update_rule(replace(right, version=2, points=('Revised instruction',)))
    after = p.context.get_context(agent, 'p', query, 'conflict-2', task_id=task.id)
    assert issue.id not in after.markdown and not after.reported_conflicts and left.id in after.markdown
    assert p.context.get_context(agent, 'p', query, 'conflict-1', task_id=task.id) == result
    with pytest.raises(ProductError):
        p.feedback.report_issue(agent, 'p', 'conflict', 'No Task', 'Missing business scope', related_rule_ids=(left.id, right.id))


def test_current_version_utility_excludes_known_zero(app):
    p, _, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Useful', ('Evidence',), ('src/**',), task_id=task.id)
    first = p.context.get_context(agent, 'p', file_query(('src/a.py',)), task_id=task.id)
    second = p.context.get_context(Actor('another'), 'p', file_query(('src/a.py',)), task_id=task.id)
    p.feedback.rate_rule(agent, first.id, rule.id, 0, 'Known')
    p.feedback.rate_rule(Actor('another'), second.id, rule.id, 5, 'Core need')
    item = next(r for r in p.ledger.project(human, 'p')['rules'] if r['id'] == rule.id)
    assert item['eval_count'] == 2 and item['known_count'] == 1 and item['avg_score'] == 5.0


def test_checklist_and_request_replay_preserve_actual_body(app):
    p, _, human, agent, task, parent, _ = app
    rule = p.knowledge.create_rule(human, 'p', 'Detailed rule', ('First clause', 'Second clause'), ('src/**',), task_id=task.id)
    query = file_query(('src/module.py',), mode='checklist')
    result = p.context.get_context(agent, 'p', query, 'checklist', task_id=task.id)
    assert '- [ ] First clause' in result.markdown and '- [ ] Second clause' in result.markdown
    assert (rule.id, 1, 'full') in result.rule_refs and result.requirement_refs[0][0] == parent.id
    assert result.task_refs == ((task.id, task.version),)
    assert p.context.get_context(agent, 'p', query, 'checklist', task_id=task.id) == result
    with pytest.raises(Conflict):
        p.context.get_context(agent, 'p', file_query(('src/module.py',), mode='detailed'), 'checklist', task_id=task.id)


def test_pause_resume_restores_testing_and_hides_only_task_knowledge(app):
    p, _, human, agent, task, parent, _ = app
    rule = p.knowledge.create_rule(human, 'p', 'Task instruction', ('Stay scoped',), ('src/**',), task_id=task.id)
    testing = update(p, agent, task, status='testing')
    paused = update(p, agent, testing, status='paused')
    assert paused.status == 'paused' and paused.paused_from == 'testing'
    during = p.context.get_context(agent, 'p', file_query(('src/a.py',)), task_id=task.id)
    assert rule.id not in during.markdown and during.scope['read_only']
    assert during.requirement_refs[0][0] == parent.id
    with pytest.raises(Conflict):
        update(p, agent, testing, status='active')
    with pytest.raises(Conflict):
        p.context.record_finding(agent, task.id, None, 'Blocked')
    restored = update(p, agent, paused, status='testing')
    assert restored.paused_from is None
    assert rule.id in p.context.get_context(agent, 'p', file_query(('src/a.py',)), task_id=task.id).markdown


def test_two_tasks_share_contracts_without_leaking_rules_or_source_scope(app):
    p, _, human, agent, first, parent, _ = app
    other = p.workspaces.create_task(agent, 'p', parent.id, 'Unrelated work')
    shared = p.knowledge.create_rule(human, 'p', 'Architecture', ('Must hold',), ('src/**',), Priority.P0)
    a = p.knowledge.create_rule(human, 'p', 'Only A', ('A only',), ('src/**',), task_id=first.id)
    b = p.knowledge.create_rule(human, 'p', 'Only B', ('B only',), ('src/**',), task_id=other.id)
    query = file_query(('src/shared.py',))
    source = {'workspace': 'C:/Work/Repo', 'machine_name': 'office', 'platform': 'windows'}
    left = p.context.get_context(agent, 'p', query, task_id=first.id, source=source)
    right = p.context.get_context(agent, 'p', query, task_id=other.id, source=source)
    unbound = p.context.get_context(agent, 'p', query, source=source)
    assert {r[0] for r in left.rule_refs} == {shared.id, a.id}
    assert {r[0] for r in right.rule_refs} == {shared.id, b.id}
    assert {r[0] for r in unbound.rule_refs} == {shared.id} and not unbound.task_refs
    with pytest.raises(ProductError):
        p.knowledge.promote_rule(agent, other.id, a.id, 1, 'Wrong Task')


def test_optional_worktree_provenance_does_not_create_a_session(app):
    p, uow, _, agent, task, *_ = app
    query = file_query(('src/a.py',))
    source = {'workspace': 'C:/Work/Repo', 'machine_name': 'Office-PC', 'platform': 'windows', 'repo_identity': 'git-common-id'}
    p.context.get_context(agent, 'p', query, task_id=task.id, source=source)
    p.context.get_context(agent, 'p', query, task_id=task.id, source={**source, 'workspace': 'c:/work/repo', 'git_branch': 'feature'})
    with uow.read() as tx:
        assert len(tx.workspaces.project_worktrees('p')) == 1
        assert not tx.c.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='sessions'").fetchall()
    with pytest.raises(Conflict):
        p.context.get_context(agent, 'p', query, task_id=task.id, source={**source, 'repo_identity': 'different-repo'})


def test_rule_evidence_deduplication_handoff_and_revision_invalidation(app):
    p, _, _, agent, task, *_ = app
    rule = p.governance.create_task_rule(agent, task.id, 'Refund guard', ('Idempotent refund',), ('src/refund.py',), 'Observed')['rule']
    other = Actor('handoff-agent')
    with pytest.raises(Conflict, match='two distinct'):
        p.governance.mutate_task_rule(other, task.id, rule['id'], 1, 'activate', 'No evidence')
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    def report(request, code=0, test_id='contract-test', actor=agent):
        stamp = start + timedelta(seconds=len(request))
        return p.governance.report_test(actor, task.id, request, ('pytest', request), ('src/refund.py',), code,
            stamp.isoformat(), (stamp + timedelta(seconds=1)).isoformat(),
            test_cases=({'test_id': test_id, 'status': 'passed' if code == 0 else 'failed'},))
    failed = report('failed', 1)
    with pytest.raises(ProductError, match='Failed or skipped'):
        p.governance.observe_rule(other, task.id, rule['id'], 1, failed.id, True, 'Invalid success')
    unrelated = report('unrelated', test_id='other-test')
    with pytest.raises(ProductError, match='declared tests'):
        p.governance.observe_rule(other, task.id, rule['id'], 1, unrelated.id, True, 'Invalid coverage')
    one = report('success-1')
    assert report('success-1', actor=other).id == one.id
    with pytest.raises(Conflict, match='already recorded'):
        p.governance.report_test(other, task.id, 'different-id', one.command, one.paths, one.exit_code, one.started_at, one.finished_at)
    state = p.governance.observe_rule(other, task.id, rule['id'], 1, one.id, True, 'Passed')
    assert state['support_count'] == 1
    assert p.governance.observe_rule(agent, task.id, rule['id'], 1, one.id, True, 'Passed') == state
    with pytest.raises(Conflict, match='two distinct'):
        p.governance.mutate_task_rule(other, task.id, rule['id'], 1, 'activate', 'Only one')
    two = report('success-2', actor=other)
    p.governance.observe_rule(agent, task.id, rule['id'], 1, two.id, True, 'Independent')
    active = p.governance.mutate_task_rule(other, task.id, rule['id'], 1, 'activate', 'Validated')['rule']
    assert active['status'] == 'active' and active['version'] == 2
    revised = p.governance.mutate_task_rule(other, task.id, rule['id'], 2, 'update', 'Changed meaning', points=('Different claim',))['rule']
    assert revised['status'] == 'draft'
    with pytest.raises(Conflict, match='after its content revision'):
        p.governance.observe_rule(agent, task.id, rule['id'], 3, one.id, True, 'Stale')
    with pytest.raises(Conflict, match='two distinct'):
        p.governance.mutate_task_rule(other, task.id, rule['id'], 3, 'activate', 'Stale evidence')


def test_contract_review_is_version_bound_and_cannot_be_self_approved(app):
    p, uow, human, agent, task, *_ = app
    contract = p.knowledge.create_rule(human, 'p', 'Original', ('Stable API',), ('src/**',), Priority.P0)
    pending = propose_review(p, agent, task.id, contract.id, 'Improved', ('Stable and authenticated',), ('src/**',), Priority.P0, 'Boundary')
    with pytest.raises(ProductError, match='human'):
        p.knowledge.review_contract(agent, 'p', pending.id, True, 'Cannot self-approve')
    stale = propose_review(p, agent, task.id, contract.id, 'Stale', ('Old proposal',), ('src/**',), Priority.P1, 'Independent')
    approved = p.knowledge.review_contract(human, 'p', pending.id, True, 'Reviewed')
    assert approved.status == 'approved' and p.knowledge.review_contract(human, 'p', pending.id, True, 'Reviewed') == approved
    with pytest.raises(Conflict, match='different input'):
        p.knowledge.review_contract(human, 'p', pending.id, False, 'Different')
    with pytest.raises(Conflict, match='changed since'):
        p.knowledge.review_contract(human, 'p', stale.id, True, 'Stale')
    with uow.read() as tx:
        assert tx.knowledge.get_rule(contract.id).points == ('Stable and authenticated',)
        assert tx.knowledge.rule_snapshot(contract.id, 1)['points'] == ['Stable API']


def test_completed_tasks_keep_rules_until_overall_acceptance_then_no_auto_restore(app):
    p, uow, human, agent, task, parent, _ = app
    rule = p.knowledge.create_rule(human, 'p', 'Task contract', ('Keep until acceptance',), ('src/**',), task_id=task.id)
    child = finish(p, agent, task)
    query = file_query(('src/a.py',))
    assert rule.id in p.context.get_context(agent, 'p', query, task_id=child.id).markdown
    current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    accepted = p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'],
        {'status': 'completed', 'completion_summary': 'User accepted'}, 'Explicit user confirmation')
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id).status == 'deprecated'
    p.requirements.manage_requirement(agent, 'p', 'update', parent.id, accepted.version, {'status': 'active'}, 'Continue')
    update(p, agent, child, status='active')
    assert rule.id not in p.context.get_context(agent, 'p', query, task_id=child.id).markdown


def test_promotion_preserves_exact_snapshot_and_allows_completed_task(app):
    p, uow, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Contract', ('Same clause',), ('src/**',), task_id=task.id)
    finish(p, agent, task)
    promoted = p.knowledge.promote_rule(Actor('handoff'), task.id, rule.id, 1, 'Reusable')
    assert promoted.task_id is None and promoted.points == rule.points and promoted.patterns == rule.patterns
    assert p.knowledge.promote_rule(agent, task.id, rule.id, 1, 'Reusable').id == promoted.id
    with pytest.raises(Conflict, match='another reason'):
        p.knowledge.promote_rule(agent, task.id, rule.id, 1, 'Other reason')
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id).status == 'deprecated'
        assert tx.knowledge.rule_snapshot(rule.id, 1)['points'] == ['Same clause']
    with pytest.raises(ProductError):
        p.knowledge.promote_rule(agent, task.id, promoted.id, 1, 'Cannot self-promote')


def test_finding_and_issue_are_directly_scoped_without_debug_gate(app):
    p, uow, _, agent, task, parent, _ = app
    finding = p.context.record_finding(agent, task.id, 'src/**', 'Possible duplication')
    query = file_query(('src/pay.py',), intent='debugging')
    delivered = p.context.get_context(agent, 'p', query, task_id=task.id)
    assert (finding.id, 1) in delivered.finding_refs and 'Unreviewed Finding' in delivered.markdown
    assert (finding.id, 1) in p.context.get_context(Actor('other'), 'p', query, task_id=task.id).finding_refs
    sibling = p.workspaces.create_task(agent, 'p', parent.id, 'Other task')
    assert finding.id not in p.context.get_context(agent, 'p', query, task_id=sibling.id).markdown
    assert finding.id not in p.context.get_context(agent, 'p', file_query(('docs/manual.md',)), task_id=task.id).markdown
    item = next(item for item in p.ledger.project(agent, 'p')['findings'] if item['id'] == finding.id)
    assert item['task_id'] == task.id and 'session_id' not in item
    issue = p.feedback.report_issue(agent, 'p', 'coverage', 'Missing rule', 'Observed behavior', 'src/pay.py', task_id=task.id)
    assert issue.task_id == task.id and p.ledger.project(agent, 'q')['findings'] == []
    with pytest.raises(ProductError):
        p.context.update_finding(agent, finding.id, 1, 'Wrong scope', resolve=True, task_id=sibling.id)


def test_opening_unknown_schema_refuses_without_writes(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        connection.execute("INSERT INTO projects VALUES('original')")
    before = path.read_bytes()
    with pytest.raises(ProductError, match='structure differs'):
        SqliteUnitOfWork(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize('change', ['rule', 'task', 'requirement', 'taxonomy'])
def test_context_rechecks_revisions_after_assembly(app, monkeypatch, change):
    import codeneuro.workflows.context as workflow
    p, _, human, agent, task, parent, _ = app
    actual, once = workflow.assemble, []
    def raced(*args, **kwargs):
        if not once:
            once.append(True)
            if change == 'rule':
                p.knowledge.create_rule(human, 'p', 'Late P0', ('New red line',), ('src/**',), Priority.P0)
            elif change == 'task':
                update(p, agent, task, description='New task scope')
            elif change == 'requirement':
                current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
                p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'], {'text': 'New overall goal'}, 'Clarified')
            else:
                p.topics.create_topic(agent, 'late-topic', 'Late', 'New boundary', 'Explicit', project_id='p')
        return actual(*args, **kwargs)
    monkeypatch.setattr(workflow, 'assemble', raced)
    result = p.context.get_context(agent, 'p', file_query(('src/new.py',)), 'race', task_id=task.id)
    expected = {'rule': 'New red line', 'task': 'New task scope', 'requirement': 'New overall goal'}
    assert len(once) == 1
    if change in expected: assert expected[change] in result.markdown
    else: assert result.taxonomy_revision == p.topics.list_topics(human, 'p')['taxonomy_revision']
