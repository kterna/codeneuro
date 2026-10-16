"""Acceptance for the independently rebuilt domain, use cases and SQLite adapter."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest
from sqlalchemy import text

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from v2_helpers import file_query as ContextQuery, configure_fixture, propose_review, LEVELS
from codeneuro.modules.knowledge import Priority, matches
from codeneuro.modules.tasks import Conflict, ProductError, TaskStatus
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product


@pytest.fixture
def app(tmp_path):
    filename = str(tmp_path / 'rebuild.db')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro',
                    'migrate', '--db', filename],
                   cwd=root, capture_output=True, text=True, check=True)
    uow = SqliteUnitOfWork(filename)
    service = Product(uow)
    human = Actor('human', 'human')
    agent = Actor('agent')
    service.workspaces.register_project(human, 'p', 'repository')
    service.workspaces.register_project(human, 'q', 'unrelated')
    configure_fixture(service, human, ('p', 'q'))
    task = service.workspaces.create_task(agent, 'p', 'Implement payment', 'Preserve refund contract')
    session = service.workspaces.start_session(agent, 'p', 'worktree-one', task.id, debug=True)
    yield service, uow, human, agent, task, session, filename
    uow.dispose()


def test_requirement_original_text_and_last_archive_are_atomic(app):
    service, uow, human, agent, task, session, _ = app
    original = 'Keep payment idempotent.\nNever silently retry transfers.'
    first = service.requirements.submit_requirement(agent, session.id, original, 'req-1')
    second = service.requirements.submit_requirement(agent, session.id, 'Add refund audit', 'req-2')
    assert service.requirements.submit_requirement(agent, session.id, original, 'req-1').id == first.id
    task_rule = service.knowledge.create_rule(human, 'p', 'Temporary', ('Write audit',), ('src/**',), task_id=task.id)
    global_rule = service.knowledge.create_rule(human, 'p', 'Permanent', ('Never lose money',), ('src/**',), Priority.P0)
    before = service.context.get_context(agent, session.id, ContextQuery(('src/pay.py',)), 'delivery-before')
    assert original.splitlines()[0] in before.markdown
    assert any(item['id'] == global_rule.id for item in before.sections['must_obey_contracts'])
    assert any(item['id'] == first.id for item in before.sections['task_actionable_checklist'])
    assert (first.id, 1) in before.requirement_refs
    service.requirements.archive_requirement(agent, session.id, first.id, 1, 'Agent confirms first completed')
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'p').status == TaskStatus.ACTIVE
    result = service.requirements.archive_requirement(agent, session.id, second.id, 1, 'Agent confirms second completed')
    assert result.status == 'archived'
    assert service.requirements.archive_requirement(agent, session.id, second.id, 1, 'Agent confirms second completed') == result
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'p').status == TaskStatus.ARCHIVED
        assert tx.knowledge.get_rule(task_rule.id).status == 'deprecated'
        assert tx.knowledge.get_rule(global_rule.id).status == 'active'
        assert tx.requirements.get_requirement(first.id, task.id).text == original
        assert tx.c.execute(text("SELECT count(*) FROM audit WHERE action='task.completed'")).scalar_one() == 1
    after = service.context.get_context(agent, session.id, ContextQuery(('src/pay.py',)), 'delivery-after')
    assert first.id not in after.markdown and second.id not in after.markdown
    assert global_rule.id in after.markdown and task_rule.id not in after.markdown


def test_reopen_preserves_history_and_only_restores_selected_requirement(app):
    service, uow, human, agent, task, session, _ = app
    first = service.requirements.submit_requirement(agent, session.id, 'Payment still needs work', 'first')
    second = service.requirements.submit_requirement(agent, session.id, 'Refund is complete', 'second')
    rule = service.knowledge.create_rule(human, 'p', 'Temporary', ('Do not revive automatically',),
                                         ('src/**',), task_id=task.id)
    with uow.write() as tx:
        tx.requirements.link_rule(first.id, rule.id)
    query = ContextQuery(('src/pay.py',))
    original_delivery = service.context.get_context(agent, session.id, query, 'before-archive')
    service.requirements.archive_requirement(agent, session.id, first.id, 1, 'Premature completion')
    service.requirements.archive_requirement(agent, session.id, second.id, 1, 'Verified refund')
    archived_task = service.workspaces.list_tasks(agent, 'p')[0]
    with pytest.raises(Conflict, match='active/testing'):
        service.workspaces.start_session(agent, 'p', 'follow-up', task.id)

    reopened_task = service.workspaces.manage_task(agent, 'p', 'update', task.id,
        archived_task.revision, {'status': 'active'}, 'User requests remaining work')
    follow_up = service.workspaces.start_session(agent, 'p', 'follow-up', task.id)
    assert reopened_task.id == task.id and reopened_task.status == TaskStatus.ACTIVE
    assert reopened_task.revision == archived_task.revision + 1
    assert follow_up.task_id == task.id
    requirements = service.requirements.list_requirements(agent, follow_up.id)
    assert {item.id for item in requirements} == {first.id, second.id}
    assert all(item.status == 'archived' and item.version == 2 for item in requirements)
    assert not service.context.get_context(agent, follow_up.id, query, 'task-only').requirement_refs

    restored = service.requirements.reopen_requirement(agent, follow_up.id, first.id, 2,
                                                       'User confirms payment is unfinished')
    assert restored.id == first.id and restored.text == first.text
    assert restored.status == 'active' and restored.version == 3 and restored.summary is None
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'p').revision == reopened_task.revision + 1
        assert tx.requirements.get_requirement(second.id, task.id).status == 'archived'
        assert tx.requirements.get_requirement(second.id, task.id).summary == 'Verified refund'
        assert tx.knowledge.get_rule(rule.id).status == 'deprecated'
        versions = tx.c.execute(text(
            'SELECT version, status, completion_summary, original_text FROM requirement_versions '
            'WHERE requirement_id=:id ORDER BY version'), {'id': first.id}).all()
        assert [tuple(row) for row in versions] == [
            (1, 'active', None, first.text),
            (2, 'archived', 'Premature completion', first.text),
            (3, 'active', None, first.text),
        ]
    delivered = service.context.get_context(agent, follow_up.id, query, 'after-reopen')
    assert delivered.requirement_refs == ((first.id, 3),)
    assert rule.id not in delivered.markdown
    assert service.context.get_context(agent, session.id, query, 'before-archive') == original_delivery
    with pytest.raises(Conflict):
        service.requirements.archive_requirement(agent, follow_up.id, first.id, 1, 'Premature completion')
    completed = service.requirements.archive_requirement(agent, follow_up.id, first.id, 3, 'Actually finished')
    assert completed.version == 4
    assert service.workspaces.list_tasks(agent, 'p')[0].status == TaskStatus.ARCHIVED


@pytest.mark.parametrize('status', ['active', 'testing'])
def test_reopen_requirement_in_working_task_preserves_other_requirements(app, status):
    service, _, human, agent, task, session, _ = app
    first = service.requirements.submit_requirement(agent, session.id, 'Recheck this', 'first')
    second = service.requirements.submit_requirement(agent, session.id, 'Still active', 'second')
    service.requirements.archive_requirement(agent, session.id, first.id, 1, 'Finished too soon')
    current = service.workspaces.list_tasks(agent, 'p')[0]
    if status == 'testing':
        current = service.workspaces.transition_task(human, 'p', task.id, current.revision,
                                                     'testing', 'Review remaining work')
    restored = service.requirements.reopen_requirement(agent, session.id, first.id, 2, 'Not done')
    assert restored.status == 'active'
    requirements = {item.id: item for item in service.requirements.list_requirements(agent, session.id)}
    assert requirements[second.id] == second
    updated = service.workspaces.list_tasks(agent, 'p')[0]
    assert updated.status == status and updated.revision == current.revision + 1


@pytest.mark.parametrize('status,target', [
    ('draft', 'released'), ('active', 'draft'), ('paused', 'released'),
    ('archived', 'testing'), ('deleted', 'active'),
])
def test_task_update_rejects_invalid_transitions(app, status, target):
    service, uow, _, agent, task, _, _ = app
    with uow.write() as tx:
        tx.c.execute(text('UPDATE tasks SET status=:status WHERE id=:id'), {'status': status, 'id': task.id})
    with pytest.raises(Conflict):
        service.workspaces.manage_task(agent, 'p', 'update', task.id, task.revision,
                                       {'status': target}, 'Change status')
    assert service.workspaces.manage_task(agent, 'p', 'get', task.id).status == status


def test_reopen_checks_versions_scope_and_explicit_reason(app):
    service, _, human, agent, task, session, _ = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Not done', 'demand')
    service.requirements.archive_requirement(agent, session.id, demand.id, 1, 'Premature')
    archived = service.workspaces.list_tasks(agent, 'p')[0]
    with pytest.raises(Conflict):
        service.workspaces.manage_task(agent, 'p', 'update', task.id,
            archived.revision - 1, {'status': 'active'}, 'Stale')
    with pytest.raises(ProductError, match='reason'):
        service.workspaces.manage_task(agent, 'p', 'update', task.id,
            archived.revision, {'status': 'active'}, ' ')
    with pytest.raises(ProductError, match='Task not found'):
        service.workspaces.manage_task(agent, 'q', 'update', task.id,
            archived.revision, {'status': 'active'}, 'Wrong project')
    with pytest.raises(Conflict, match='Task before'):
        service.requirements.reopen_requirement(agent, session.id, demand.id, 2, 'Task still archived')
    reopened = service.workspaces.manage_task(agent, 'p', 'update', task.id,
        archived.revision, {'status': 'active'}, 'Continue')
    with pytest.raises(Conflict):
        service.workspaces.manage_task(agent, 'p', 'update', task.id,
            archived.revision, {'status': 'active'}, 'Retry')
    with pytest.raises(Conflict):
        service.requirements.reopen_requirement(agent, session.id, demand.id, 1, 'Stale')
    with pytest.raises(ProductError, match='reason'):
        service.requirements.reopen_requirement(agent, session.id, demand.id, 2, ' ')

    for project in ('p', 'q'):
        other = service.workspaces.create_task(agent, project, 'Unrelated')
        other_session = service.workspaces.start_session(agent, project, f'other-{project}', other.id)
        assert service.requirements.list_requirements(agent, other_session.id) == []
        with pytest.raises(ProductError, match='outside this Task'):
            service.requirements.reopen_requirement(agent, other_session.id, demand.id, 2, 'Wrong Task')
    unbound = service.workspaces.start_session(agent, 'p', 'unbound')
    with pytest.raises(ProductError, match='Select a Task'):
        service.requirements.list_requirements(agent, unbound.id)
    with pytest.raises(ProductError, match='outside this Task'):
        service.requirements.reopen_requirement(agent, unbound.id, demand.id, 2, 'No Task')
    with pytest.raises(ProductError, match='outside this Task'):
        service.requirements.reopen_by_human(human, 'q', task.id, demand.id, 2, 'Wrong project')
    with pytest.raises(ProductError, match='Human review'):
        service.requirements.reopen_by_human(agent, 'p', task.id, demand.id, 2, 'Wrong entry')

    paused = service.workspaces.pause_task(human, 'p', task.id, reopened.revision, 'Wait')
    with pytest.raises(Conflict, match='Task before'):
        service.requirements.reopen_requirement(agent, session.id, demand.id, 2, 'Still paused')
    service.workspaces.resume_task(human, 'p', task.id, paused.revision, 'Continue')
    restored = service.requirements.reopen_requirement(agent, session.id, demand.id, 2, 'Continue')
    with pytest.raises(Conflict):
        service.requirements.reopen_requirement(agent, session.id, demand.id, 2, 'Retry')
    with pytest.raises(Conflict):
        service.requirements.reopen_requirement(agent, session.id, demand.id, restored.version, 'Already active')


@pytest.mark.parametrize('overrides', [
    {'entity_id': None}, {'expected_version': None}, {'reason': ' '},
    {'changes': {}}, {'action': 'get'}, {'action': 'delete'},
])
def test_crud_rejects_missing_or_irrelevant_arguments(app, overrides):
    service, uow, _, agent, task, session, _ = app
    options = {'action': 'update', 'entity_id': task.id, 'expected_version': task.revision,
               'changes': {'status': 'testing'}, 'reason': 'Review'}
    options.update(overrides)
    with pytest.raises(ProductError):
        service.workspaces.manage_task(agent, 'p', **options)
    assert service.workspaces.list_tasks(agent, 'p')[0] == task
    with uow.read() as tx:
        assert tx.c.execute(text('SELECT count(*) FROM sessions')).scalar_one() == 1
        assert tx.c.execute(text('SELECT count(*) FROM worktrees')).scalar_one() == 1


@pytest.mark.parametrize('action', ['task.reopened', 'requirement.reopened'])
def test_reopen_audit_failure_rolls_back_state_and_version(app, action):
    service, uow, _, agent, task, session, _ = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Pending work', 'demand')
    service.requirements.archive_requirement(agent, session.id, demand.id, 1, 'Premature')
    current = service.workspaces.list_tasks(agent, 'p')[0]
    if action == 'requirement.reopened':
        current = service.workspaces.manage_task(agent, 'p', 'update', task.id,
            current.revision, {'status': 'active'}, 'Continue')
    with uow.write() as tx:
        before = {table: tx.c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()
                  for table in ('sessions', 'worktrees', 'audit')}
        tx.c.execute(text(
            f"CREATE TRIGGER reject_reopen BEFORE INSERT ON audit WHEN NEW.action='{action}' "
            "BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
    with pytest.raises(Exception, match='injected failure'):
        if action == 'requirement.reopened':
            service.requirements.reopen_requirement(agent, session.id, demand.id, 2, 'Continue')
        else:
            service.workspaces.manage_task(agent, 'p', 'update', task.id,
                current.revision, {'status': 'active'}, 'Continue')
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'p') == current
        requirement = tx.requirements.get_requirement(demand.id, task.id)
        assert requirement.status == 'archived' and requirement.version == 2
        assert requirement.summary == 'Premature'
        assert tx.c.execute(text('SELECT count(*) FROM requirement_versions WHERE requirement_id=:id'),
                            {'id': demand.id}).scalar_one() == 2
        for table, count in before.items():
            assert tx.c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == count


def test_scope_feedback_and_p0_survive_filter_and_budget(app):
    service, uow, human, agent, task, session, _ = app
    p0 = service.knowledge.create_rule(human, 'p', 'P0 guard', ('CRITICAL' * 160,), ('src/**',), Priority.P0)
    p1 = service.knowledge.create_rule(human, 'p', 'Business', ('Needed',), ('src/**',), Priority.P1)
    other = service.knowledge.create_rule(human, 'p', 'Other folder', ('Not here',), ('tests/**',))
    q = ContextQuery(('src/main.py',), priorities=(Priority.P0,), max_chars=512)
    delivered = service.context.get_context(agent, session.id, q, 'budgeted')
    assert delivered.budget_exceeded and 'CRITICAL' * 160 in delivered.markdown
    assert [ref[0] for ref in delivered.rule_refs] == [p0.id]
    assert other.id not in delivered.markdown
    full = service.context.get_context(agent, session.id, ContextQuery(('src/main.py',)), 'full')
    assert p1.id in full.markdown
    assert service.feedback.rate_rule(agent, session.id, full.id, p1.id, 0)['duplicate'] is False
    assert service.feedback.rate_rule(agent, session.id, full.id, p1.id, 0)['duplicate'] is True
    reminder = service.context.get_context(agent, session.id, ContextQuery(('src/main.py',)), 'known')
    assert any(ref[0] == p1.id and ref[2] == 'reminder' for ref in reminder.rule_refs)
    assert any(ref[0] == p0.id and ref[2] == 'full' for ref in reminder.rule_refs)
    assert matches('src/**', 'src/main.py') and not matches('src/*.py', 'src/deep/main.py')


def test_scope_density_counts_only_actual_active_rules_without_inventing_files(app):
    service, _, human, agent, task, session, _ = app
    service.knowledge.create_rule(human, 'p', 'Architecture', ('Keep invariants',), ('src/**',), Priority.P0)
    service.knowledge.create_rule(human, 'p', 'Task', ('Complete work',), ('src/pay/**',),
                                  Priority.P1, task_id=task.id)
    ledger = service.ledger.project(human, 'p')
    assert [scope['scope'] for scope in ledger['scope_density']] == ['src', 'src/pay']
    assert ledger['scope_density'][0]['p0'] == 1
    assert ledger['scope_density'][1]['short_term'] == 1
    assert ledger['scope_density'][1]['rule_ids']
    assert all('files' not in scope for scope in ledger['scope_density'])


def test_reported_conflict_only_refs_current_delivered_versions(app):
    service, uow, human, agent, task, session, _ = app
    left = service.knowledge.create_rule(human, 'p', 'Keep signed payload',
        ('Always sign payload',), ('src/**',), Priority.P0)
    right = service.knowledge.create_rule(human, 'p', 'Task instruction',
        ('Check auth changes',), ('src/**',), task_id=task.id)
    issue = service.feedback.report_issue(agent, session.id, 'conflict',
        'Potentially conflicting instructions', 'Agent noticed a contradiction',
        'src/api.py', (left.id, right.id))
    result = service.context.get_context(agent, session.id, ContextQuery(('src/api.py',)), 'conflict-1')
    assert result.conflict_assessment == 'not_assessed'  # Report != semantic model diagnosis.
    assert issue.id in result.markdown
    assert result.reported_conflicts[0]['rule_refs'] == ((left.id, 1), (right.id, 1))
    assert service.context.get_context(agent, session.id,
        ContextQuery(('src/api.py',)), 'conflict-1') == result
    with uow.write() as tx:
        old = tx.knowledge.get_rule(right.id)
        tx.knowledge.update_rule(replace(old, version=2, points=('Revised task instruction',)))
    after = service.context.get_context(agent, session.id, ContextQuery(('src/api.py',)), 'conflict-2')
    assert issue.id not in after.markdown and not after.reported_conflicts
    assert left.id in after.markdown  # P0 unaffected by advisory issue or revision.


def test_ledger_current_version_utility_excludes_known_zero(app):
    service, _, human, agent, task, session, _ = app
    rule = service.knowledge.create_rule(human, 'p', 'Useful', ('Evidence',), ('src/**',), task_id=task.id)
    other = service.workspaces.start_session(agent, 'p', 'second-worktree', task.id, debug=True)
    first = service.context.get_context(agent, session.id, ContextQuery(('src/a.py',)), 'score-0')
    second = service.context.get_context(agent, other.id, ContextQuery(('src/a.py',)), 'score-5')
    service.feedback.rate_rule(agent, session.id, first.id, rule.id, 0, 'Already known')
    service.feedback.rate_rule(agent, other.id, second.id, rule.id, 5, 'Core need')
    item = next(r for r in service.ledger.project(human, 'p')['rules'] if r['id'] == rule.id)
    assert item['eval_count'] == 2 and item['known_count'] == 1 and item['avg_score'] == 5.0


def test_checklist_preserves_full_clauses_and_same_query_retries(app):
    service, _, human, agent, task, session, _ = app
    rule = service.knowledge.create_rule(human, 'p', 'Detailed rule', ('First clause', 'Second clause'),
                                         ('src/**',), task_id=task.id)
    demand = service.requirements.submit_requirement(agent, session.id, 'Original instruction', 'task-item')
    query = ContextQuery(('src/module.py',), mode='checklist')
    result = service.context.get_context(agent, session.id, query, 'checklist')
    assert '- [ ] First clause' in result.markdown
    assert '- [ ] Second clause' in result.markdown
    assert '- [ ] Original instruction' in result.markdown
    assert (rule.id, 1, 'full') in result.rule_refs
    assert (demand.id, 1) in result.requirement_refs
    replay = service.context.get_context(agent, session.id, query, 'checklist')
    assert replay.id == result.id and replay.sections == result.sections
    with pytest.raises(Conflict):
        service.context.get_context(agent, session.id, ContextQuery(('src/module.py',), mode='detailed'), 'checklist')


def test_versions_idempotence_and_unscoped_projects(app):
    service, _, _, agent, task, session, _ = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Do it', 'once')
    with pytest.raises(Conflict):
        service.requirements.submit_requirement(agent, session.id, 'Something else', 'once')
    first = service.context.get_context(agent, session.id, ContextQuery(('src/a.py',)), 'same')
    assert service.context.get_context(agent, session.id, ContextQuery(('src/a.py',)), 'same').id == first.id
    with pytest.raises(Conflict):
        service.context.get_context(agent, session.id, ContextQuery(('src/b.py',)), 'same')
    with pytest.raises(Conflict):
        service.requirements.archive_requirement(agent, session.id, demand.id, 3, 'Complete')
    assert service.workspaces.start_session(agent, 'q', 'other', None).project_id == 'q'


@pytest.mark.parametrize('blocked_status', ['paused', 'released'])
def test_archiving_final_requirement_requires_active_or_testing_task(app, blocked_status):
    service, uow, _, agent, task, session, _ = app
    item = service.requirements.submit_requirement(agent, session.id, 'Do not skip states', 'req')
    with uow.write() as tx:
        tx.c.execute(text('UPDATE tasks SET status=:state, revision=revision+1 WHERE id=:id'),
                     {'state':blocked_status, 'id':task.id})
    with pytest.raises(Conflict, match='paused/released'):
        service.requirements.archive_requirement(agent, session.id, item.id, 1, 'Agent confirmed')
    with uow.read() as tx:
        assert tx.requirements.get_requirement(item.id, task.id).status == 'active'
        assert tx.workspaces.get_task(task.id, 'p').status == blocked_status


def test_pause_resume_restores_testing_and_blocks_archival_while_paused(app):
    service, uow, human, agent, task, session, _ = app
    item = service.requirements.submit_requirement(agent, session.id, 'Test lifecycle', 'r')
    rule = service.knowledge.create_rule(human, 'p', 'Task instruction', ('Stay scoped',), ('src/**',), task_id=task.id)
    with uow.write() as tx:
        tx.c.execute(text('UPDATE tasks SET status=:status, revision=revision+1 WHERE id=:id'),
                     {'status': 'testing', 'id': task.id})
    current = service.workspaces.list_tasks(agent, 'p')[0]
    paused = service.workspaces.pause_task(human, 'p', task.id, current.revision, 'Temporarily blocked')
    assert paused.status == TaskStatus.PAUSED and paused.paused_from == TaskStatus.TESTING
    with pytest.raises(Conflict, match='paused/released'):
        service.requirements.archive_requirement(agent, session.id, item.id, 1, 'Not yet')
    during = service.context.get_context(agent, session.id, ContextQuery(('src/a.py',)), 'paused')
    assert rule.id not in during.markdown and item.id not in during.markdown
    with pytest.raises(Conflict):
        service.workspaces.resume_task(human, 'p', task.id, current.revision, 'Stale revision')
    restored = service.workspaces.resume_task(human, 'p', task.id, paused.revision, 'Issue resolved')
    assert restored.status == TaskStatus.TESTING and restored.paused_from is None
    assert rule.id in service.context.get_context(agent, session.id, ContextQuery(('src/a.py',)), 'restored').markdown


def test_two_worktrees_share_contracts_but_never_leak_task_rules(app):
    service, _, human, agent, task_a, session_a, _ = app
    task_b = service.workspaces.create_task(agent, 'p', 'Unrelated backend')
    session_b = service.workspaces.start_session(agent, 'p', 'worktree-two', task_b.id, debug=True)
    assert session_a.worktree_id != session_b.worktree_id
    long_term = service.knowledge.create_rule(human, 'p', 'Architecture', ('Must hold',),
                                              ('src/**',), Priority.P0)
    short_a = service.knowledge.create_rule(human, 'p', 'Only A', ('A only',),
                                           ('src/**',), task_id=task_a.id)
    short_b = service.knowledge.create_rule(human, 'p', 'Only B', ('B only',),
                                           ('src/**',), task_id=task_b.id)
    query = ContextQuery(('src/shared.py',))
    a = service.context.get_context(agent, session_a.id, query)
    b = service.context.get_context(agent, session_b.id, query)
    assert {r[0] for r in a.rule_refs} == {long_term.id, short_a.id}
    assert {r[0] for r in b.rule_refs} == {long_term.id, short_b.id}
    with pytest.raises(ProductError):
        service.knowledge.promote_rule(agent, session_b.id, short_a.id, 1, 'Wrong Task')


def test_client_attested_worktree_identity_is_stable_and_cannot_be_rebound(app):
    service, uow, _, agent, task, _, _ = app
    args = dict(machine_name='Office-PC', platform='windows', repo_identity='git-common-id')
    first = service.workspaces.start_session(agent, 'p', 'C:/Work/Repo', task.id, **args)
    repeated = service.workspaces.start_session(agent, 'p', 'c:/work/repo', task.id, **args)
    assert first.worktree_id == repeated.worktree_id
    with pytest.raises(Conflict, match='cannot be rebound'):
        service.workspaces.start_session(agent, 'p', 'C:/Work/Repo', task.id,
            machine_name='Office-PC', platform='windows', repo_identity='a-different-repository')
    with uow.read() as tx:
        worktrees = tx.workspaces.project_worktrees('p')
        assert len(worktrees) == 2  # Initial fixture worktree plus this attested worktree.
        assert any(w.id == first.worktree_id and w.repo_identity == 'git-common-id' for w in worktrees)


def test_agent_rule_requires_two_distinct_reported_tests_and_rechecks_after_edit(app):
    service, _, human, agent, task, session, _ = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Improve refund', 'demand')
    created = service.governance.create_task_rule(agent, session.id, 'Guard refund',
        ('Refund idempotently',), ('src/refund.py',), 'Observed in this task',
        requirement_id=demand.id)
    rule = created['rule']
    assert rule['status'] == 'draft'
    assert rule['id'] not in service.context.get_context(agent, session.id,
        ContextQuery(('src/refund.py',)), 'before-evidence').markdown
    with pytest.raises(Conflict, match='two distinct'):
        service.governance.mutate_task_rule(agent, session.id, rule['id'], 1,
            'activate', 'Guess this is true')
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    def report(request_id, exit_code=0, path='src/refund.py'):
        stamp = start + timedelta(seconds=len(request_id))
        cases = ({'test_id': 'other-test' if request_id == 'unrelated' else 'contract-test',
                  'status': 'passed' if exit_code == 0 else 'failed'},)
        return service.governance.report_test(agent, session.id, request_id,
            ('pytest', request_id), (path,), exit_code, stamp.isoformat(),
            (stamp + timedelta(seconds=1)).isoformat(), test_cases=cases)
    failed = report('failing', 1)
    with pytest.raises(ProductError, match='Failed or skipped'):
        service.governance.observe_rule(agent, session.id, rule['id'], 1, failed.id,
                                        True, 'Cannot claim success')
    unrelated = report('unrelated', path='tests/other.py')
    with pytest.raises(ProductError, match='declared tests'):
        service.governance.observe_rule(agent, session.id, rule['id'], 1, unrelated.id,
                                        True, 'Not the Rule path')
    one = report('successful-1')
    assert service.governance.report_test(agent, session.id, 'successful-1',
        ('pytest', 'successful-1'), ('src/refund.py',), 0,
        (start + timedelta(seconds=len('successful-1'))).isoformat(),
        (start + timedelta(seconds=len('successful-1') + 1)).isoformat()).id == one.id
    with pytest.raises(Conflict, match='same reported test'):
        service.governance.report_test(agent, session.id, 'another-request',
            ('pytest', 'successful-1'), ('src/refund.py',), 0,
            (start + timedelta(seconds=len('successful-1'))).isoformat(),
            (start + timedelta(seconds=len('successful-1') + 1)).isoformat())
    state = service.governance.observe_rule(agent, session.id, rule['id'], 1,
        one.id, True, 'Passing test covers refund')
    assert state['support_count'] == 1
    with pytest.raises(Conflict, match='two distinct'):
        service.governance.mutate_task_rule(agent, session.id, rule['id'], 1,
            'activate', 'Only one successful report')
    two = report('successful-2')
    service.governance.observe_rule(agent, session.id, rule['id'], 1,
        two.id, True, 'Second independent report')
    active = service.governance.mutate_task_rule(agent, session.id, rule['id'], 1,
        'activate', 'Validated twice')['rule']
    assert active['status'] == 'active' and active['version'] == 2
    assert rule['id'] in service.context.get_context(agent, session.id,
        ContextQuery(('src/refund.py',)), 'after-evidence').markdown
    revised = service.governance.mutate_task_rule(agent, session.id, rule['id'], 2,
        'update', 'Change meaning', points=('Different claim',))['rule']
    assert revised['status'] == 'draft' and revised['version'] == 3
    with pytest.raises(Conflict, match='after its content revision'):
        service.governance.observe_rule(agent, session.id, rule['id'], 3,
            one.id, True, 'Old report cannot validate new content')
    with pytest.raises(Conflict, match='two distinct'):
        service.governance.mutate_task_rule(agent, session.id, rule['id'], 3,
            'activate', 'Old evidence is stale')


def test_existing_long_term_contract_requires_human_review_and_version_match(app):
    service, uow, human, agent, task, session, _ = app
    contract = service.knowledge.create_rule(human, 'p', 'Original', ('Keep API stable',), ('src/**',), Priority.P0)
    pending = propose_review(service, agent, session.id, contract.id,
        'Improved contract', ('Keep the API stable and authenticated',),
        ('src/**',), Priority.P0, 'Observed new boundary')
    with uow.read() as tx:
        assert tx.knowledge.get_rule(contract.id).version == 1
    with pytest.raises(ProductError, match='human'):
        service.knowledge.review_contract(agent, 'p', pending.id, True, 'Agent cannot self-approve')
    stale = propose_review(service, agent, session.id, contract.id,
        'Stale suggestion', ('Old proposed text',), ('src/**',), Priority.P1,
        'Independent proposal')
    approved = service.knowledge.review_contract(human, 'p', pending.id, True, 'Reviewed clauses and scope')
    assert approved.status == 'approved'
    assert service.knowledge.review_contract(human, 'p', pending.id, True, 'Reviewed clauses and scope') == approved
    with pytest.raises(Conflict, match='different input'):
        service.knowledge.review_contract(human, 'p', pending.id, False, 'Different decision')
    with pytest.raises(Conflict, match='changed since'):
        service.knowledge.review_contract(human, 'p', stale.id, True, 'Stale version')
    with uow.read() as tx:
        revised = tx.knowledge.get_rule(contract.id)
        assert revised.version == 2 and revised.points == ('Keep the API stable and authenticated',)
        assert tx.c.execute(text('SELECT count(*) FROM rule_versions WHERE rule_id=:rid'),
                            {'rid':contract.id}).scalar_one() == 2


def test_archiving_one_requirement_deactivates_its_linked_rule_only(app):
    service, uow, human, agent, task, session, _ = app
    linked = service.requirements.submit_requirement(agent, session.id, 'Implement refund', 'linked')
    other = service.requirements.submit_requirement(agent, session.id, 'Implement chargeback', 'other')
    created = service.governance.create_task_rule(agent, session.id, 'Refund guard',
        ('Check idempotency',), ('src/refund.py',), 'Required by refund', requirement_id=linked.id)
    rule_id = created['rule']['id']
    start = datetime.now(timezone.utc)
    for i in range(2):
        stamp = (start + timedelta(seconds=i)).isoformat()
        report = service.governance.report_test(agent, session.id, f'run-{i}',
            ('pytest', f'case-{i}'), ('src/refund.py',), 0, stamp, stamp)
        service.governance.observe_rule(agent, session.id, rule_id, 1,
            report.id, True, 'Client-reported case passed')
    active = service.governance.mutate_task_rule(agent, session.id, rule_id, 1,
        'activate', 'Supported by two distinct reports')['rule']
    assert active['status'] == 'active'
    service.requirements.archive_requirement(agent, session.id, linked.id, 1, 'Agent confirmed refund')
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'p').status == TaskStatus.ACTIVE
        assert tx.knowledge.get_rule(rule_id).status == 'deprecated'
        assert tx.requirements.get_requirement(other.id, task.id).status == 'active'
    assert rule_id not in service.context.get_context(agent, session.id,
        ContextQuery(('src/refund.py',)), 'after-linked-archive').markdown


def test_promotion_preserves_original_and_never_changes_existing_contract(app):
    service, uow, human, agent, task, session, _ = app
    source = service.knowledge.create_rule(human, 'p', 'Contract', ('Same clause',), ('src/**',),
                                 Priority.P1, task.id)
    promoted = service.knowledge.promote_rule(agent, session.id, source.id, 1, 'Reusable across Tasks')
    assert promoted.task_id is None and promoted.points == source.points
    assert promoted.patterns == source.patterns and promoted.priority == source.priority
    assert service.knowledge.promote_rule(agent, session.id, source.id, 1, 'Reusable across Tasks').id == promoted.id
    with pytest.raises(Conflict, match='another reason'):
        service.knowledge.promote_rule(agent, session.id, source.id, 1, 'Different reason')
    with uow.read() as tx:
        assert tx.knowledge.get_rule(source.id).status == 'deprecated'
        assert tx.knowledge.get_rule(source.id).version == 2
        assert tx.knowledge.get_rule(promoted.id).origin_reason == 'Reusable across Tasks'
        assert tx.c.execute(text('SELECT count(*) FROM rules WHERE origin_rule_id=:rid'), {'rid': source.id}).scalar_one() == 1
    with pytest.raises(ProductError):
        service.knowledge.promote_rule(agent, session.id, promoted.id, 1, 'Cannot self-promote long-term rule')


def test_concurrent_final_requirement_archive_exactly_once(app):
    service, uow, _, agent, task, session, filename = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Finish', 'req')
    second = SqliteUnitOfWork(filename)
    barrier = threading.Barrier(2)
    def complete(current):
        barrier.wait()
        return Product(current).requirements.archive_requirement(agent, session.id, demand.id, 1, 'Done').id
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(complete, source) for source in (uow, second)]
            assert [job.result(timeout=15) for job in jobs] == [demand.id, demand.id]
        with uow.read() as tx:
            assert tx.workspaces.get_task(task.id, 'p').status == TaskStatus.ARCHIVED
            assert tx.c.execute(text("SELECT count(*) FROM audit WHERE action='task.completed'")).scalar_one() == 1
    finally:
        second.dispose()


def test_failed_audit_rolls_back_requirement_and_task(app):
    service, uow, _, agent, task, session, _ = app
    demand = service.requirements.submit_requirement(agent, session.id, 'Finish', 'req')
    with uow.write() as tx:
        tx.c.execute(text("CREATE TRIGGER reject_archival BEFORE INSERT ON audit WHEN NEW.action='requirement.archived' BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
    with pytest.raises(Exception, match='injected failure'):
        service.requirements.archive_requirement(agent, session.id, demand.id, 1, 'Done')
    with uow.read() as tx:
        assert tx.requirements.get_requirement(demand.id, task.id).status == 'active'
        assert tx.workspaces.get_task(task.id, 'p').status == TaskStatus.ACTIVE


def test_finding_is_task_scoped_across_sessions_and_issue_is_debug_only(app):
    service, uow, _, agent, task, session, _ = app
    finding = service.context.record_finding(agent, session.id, 'src/**', 'Refunds may duplicate', Priority.P1)
    query = ContextQuery(('src/pay.py',), intent='debugging')
    delivered = service.context.get_context(agent, session.id, query, 'debugging')
    assert finding.id in delivered.markdown
    assert (finding.id, 1) in delivered.finding_refs
    assert delivered.sections['module_gotchas'][0]['kind'] == 'finding'
    another = service.workspaces.start_session(agent, 'p', 'worktree-two', task.id, debug=True)
    shared = service.context.get_context(agent, another.id, query, 'other')
    assert (finding.id, 1) in shared.finding_refs
    assert 'Unreviewed Finding' in shared.markdown
    assert finding.id not in service.context.get_context(agent, another.id,
        ContextQuery(('docs/manual.md',), intent='debugging'), 'different-path').markdown
    unrelated = service.workspaces.create_task(agent, 'p', 'Other task')
    unrelated_session = service.workspaces.start_session(agent, 'p', 'worktree-three', unrelated.id)
    assert finding.id not in service.context.get_context(agent, unrelated_session.id, query, 'other-task').markdown
    ledger = service.ledger.project(agent, 'p')
    assert any(item['id'] == finding.id and item['status'] == 'pending_review'
               and item['task_id'] == task.id and item['session_id'] == session.id
               for item in ledger['findings'])
    assert service.ledger.project(agent, 'q')['findings'] == []
    issue = service.feedback.report_issue(agent, session.id, 'coverage', 'Missing module rule',
                                 'Observed uncovered behavior', 'src/pay.py')
    with uow.read() as tx:
        assert tx.c.execute(text('SELECT count(*) FROM issues WHERE id=:id'), {'id': issue.id}).scalar_one() == 1
    plain = service.workspaces.start_session(agent, 'p', 'worktree-one', task.id, debug=False)
    with pytest.raises(ProductError, match='Debug'):
        service.feedback.report_issue(agent, plain.id, 'coverage', 'Bad', 'Bad', 'src/pay.py')


def test_opening_legacy_or_unknown_schema_is_refused_without_writes(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        connection.execute("INSERT INTO projects VALUES('original')")
    before = path.read_bytes()
    with pytest.raises(ProductError, match='legacy'):
        SqliteUnitOfWork(str(path))
    assert path.read_bytes() == before


def test_revalidate_project_revision_when_p0_created_mid_assembly(app, monkeypatch):
    import codeneuro.workflows.context as workflow
    service, _, human, agent, _, session, _ = app
    actual = workflow.assemble
    once = []
    def raced(*args, **kwargs):
        if not once:
            once.append(True)
            service.knowledge.create_rule(human, 'p', 'Late P0', ('New red line',), ('src/**',), Priority.P0)
        return actual(*args, **kwargs)
    monkeypatch.setattr(workflow, 'assemble', raced)
    result = service.context.get_context(agent, session.id, ContextQuery(('src/new.py',)), 'race')
    assert len(once) == 1 and 'New red line' in result.markdown
