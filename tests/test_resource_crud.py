"""Requirement and Task CRUD preserves versions, scope, acceptance and history."""
import pytest

from codeneuro.modules.tasks import Conflict, ProductError
from test_product_core import app, finish, update
from helpers import file_query


def test_task_metadata_versions_pause_resume_and_project_boundary(app):
    p, _, _, agent, task, *_ = app
    changed = update(p, agent, task, title='Revised task', description='More detail', status='testing')
    assert changed.version == 2 and changed.description == 'More detail'
    paused = update(p, agent, changed, status='paused')
    assert paused.paused_from == 'testing'
    with pytest.raises(Conflict): update(p, agent, paused, status='active')
    resumed = update(p, agent, paused, status='testing')
    assert resumed.paused_from is None
    with pytest.raises(Conflict):
        p.workspaces.manage_task(agent, 'p', 'delete', task.id, 1, reason='Stale')
    with pytest.raises(ProductError, match='not found'):
        p.workspaces.manage_task(agent, 'q', 'get', task.id)


def test_requirement_original_text_versions_and_delivery_replay(app):
    p, uow, _, agent, task, parent, _ = app
    query = file_query(('src/pay.py',))
    old = p.context.get_context(agent, 'p', query, 'original-delivery', task_id=task.id)
    current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    revised = p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'],
                                                {'text': 'Revised overall goal'}, 'New acceptance criteria')
    assert revised.original_text == parent.original_text
    assert p.context.get_context(agent, 'p', query, 'original-delivery', task_id=task.id) == old
    fresh = p.context.get_context(agent, 'p', query, task_id=task.id)
    assert fresh.requirement_refs == ((parent.id, revised.version),) and revised.text in fresh.markdown
    detail = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    assert detail['history'][0]['text'] == parent.text and detail['history'][-1]['text'] == revised.text
    with pytest.raises(Conflict):
        p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'], {'text': 'Stale'}, 'Stale')
    with pytest.raises(ProductError): p.requirements.manage_requirement(agent, 'q', 'get', parent.id)
    with uow.read() as tx:
        assert tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []


def test_deleted_tasks_preserve_deliveries_and_do_not_complete_parent(app):
    p, uow, human, agent, task, parent, _ = app
    local = p.knowledge.create_rule(human, 'p', 'Local', ('Task rule',), ('src/**',), task_id=task.id)
    shared = p.knowledge.create_rule(human, 'p', 'Shared', ('Project rule',), ('src/**',))
    p.context.record_finding(agent, task.id, 'src/**', 'Owned finding')
    query = file_query(('src/pay.py',))
    old = p.context.get_context(agent, 'p', query, 'before-delete', task_id=task.id)
    deleted = p.workspaces.manage_task(agent, 'p', 'delete', task.id, task.version, reason='Withdraw scope')
    assert deleted.deleted_at and deleted.status == 'active'
    assert p.workspaces.manage_task(agent, 'p', 'list')['items'] == []
    assert p.workspaces.manage_task(agent, 'p', 'get', task.id)['history'][-1]['deleted_at']
    current_parent = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    assert current_parent['status'] == 'active' and current_parent['progress'] == {'total': 0, 'completed': 0}
    with pytest.raises(ProductError): p.context.get_context(agent, 'p', query, task_id=task.id)
    assert p.context.get_context(agent, 'p', query, 'before-delete', task_id=task.id) == old
    assert {ref[0] for ref in p.context.get_context(agent, 'p', query).rule_refs} == {shared.id}
    with uow.read() as tx:
        assert tx.knowledge.get_rule(local.id).status == 'deprecated'
        assert tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
    removed = p.requirements.manage_requirement(agent, 'p', 'delete', parent.id, current_parent['version'], reason='Withdraw parent')
    assert removed.deleted_at and removed.status == 'active'
    assert p.requirements.manage_requirement(agent, 'p', 'get', parent.id)['original_text'] == parent.original_text
    assert p.requirements.manage_requirement(agent, 'p', 'list')['items'] == []


def test_archived_unfinished_child_still_blocks_overall_acceptance(app):
    p, _, human, agent, task, parent, _ = app
    other = p.workspaces.create_task(agent, 'p', parent.id, 'Unfinished')
    finish(p, agent, task)
    archived = update(p, agent, other, archived=True)
    current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    assert current['status'] == 'active' and current['progress'] == {'total': 2, 'completed': 1}
    with pytest.raises(Conflict):
        p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'], {'status': 'accepting'}, 'Cannot skip')
    with pytest.raises(Conflict): update(p, agent, archived, description='Read only')
    restored = update(p, agent, archived, archived=False)
    assert restored.status == 'active'


@pytest.mark.parametrize('event', ['task.created', 'task.updated', 'task.deleted',
                                   'requirement.created', 'requirement.updated', 'requirement.deleted'])
def test_failed_audit_rolls_back_data_snapshots_and_parent_versions(app, event):
    p, uow, _, agent, task, parent, _ = app
    empty = p.requirements.manage_requirement(agent, 'p', 'create', changes={'title': 'Empty', 'text': 'Original'})
    before_task = p.workspaces.manage_task(agent, 'p', 'get', task.id)
    before_parent = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    with uow.write() as tx:
        before_counts = {name: tx.c.exec_driver_sql(f'SELECT COUNT(*) FROM {name}').scalar() for name in
                         ('tasks', 'task_versions', 'requirements', 'requirement_versions', 'request_receipts')}
        tx.c.exec_driver_sql(f"CREATE TRIGGER reject_crud BEFORE INSERT ON audit WHEN NEW.action='{event}' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    with pytest.raises(Exception, match='injected failure'):
        if event == 'task.created':
            p.workspaces.create_task(agent, 'p', parent.id, 'Rollback', request_id='rollback-create')
        elif event.startswith('task.'):
            p.workspaces.manage_task(agent, 'p', 'delete' if event.endswith('deleted') else 'update',
                task.id, task.version, None if event.endswith('deleted') else {'description': 'Changed'}, 'Change')
        elif event == 'requirement.created':
            p.requirements.manage_requirement(agent, 'p', 'create', changes={'title': 'Rollback', 'text': 'New'}, request_id='rollback-create')
        else:
            p.requirements.manage_requirement(agent, 'p', 'delete' if event.endswith('deleted') else 'update',
                empty.id, empty.version, None if event.endswith('deleted') else {'text': 'Changed'}, 'Change')
    assert p.workspaces.manage_task(agent, 'p', 'get', task.id) == before_task
    assert p.requirements.manage_requirement(agent, 'p', 'get', parent.id) == before_parent
    with uow.read() as tx:
        assert all(tx.c.exec_driver_sql(f'SELECT COUNT(*) FROM {name}').scalar() == count for name, count in before_counts.items())


@pytest.mark.parametrize('changes', [{'status': 'released'}, {'status': 'archived'}, {'requirement_id': 'other'},
                                     {'archived': 'true'}, {'title': ''}, {'verification_summary': 'Not verifying'}])
def test_task_rejects_old_states_reparenting_and_irrelevant_changes(app, changes):
    p, _, _, agent, task, *_ = app
    with pytest.raises(ProductError): update(p, agent, task, **changes)


@pytest.mark.parametrize('action,arguments', [
    ('get', {}), ('create', {'entity_id': 'supplied'}), ('list', {'changes': {'title': 'Extra'}}),
    ('update', {'entity_id': 'unknown', 'expected_version': 0, 'changes': {'title': 'Bad'}, 'reason': 'Reason'}),
    ('delete', {'entity_id': 'unknown', 'expected_version': 1}),
])
def test_crud_rejects_missing_or_irrelevant_arguments(app, action, arguments):
    p, _, _, agent, *_ = app
    for manager in (p.requirements.manage_requirement, p.workspaces.manage_task):
        with pytest.raises(ProductError): manager(agent, 'p', action, **arguments)


def test_completed_child_scope_requires_reopen_while_title_does_not(app):
    p, _, _, agent, task, parent, _ = app
    completed = finish(p, agent, task)
    renamed = update(p, agent, completed, title='Clearer title')
    assert renamed.status == 'completed' and renamed.verification_summary
    for change in ({'description': 'New scope'}, {'acceptance_criteria': 'New checks'}):
        with pytest.raises(Conflict): update(p, agent, renamed, **change)
    reopened = update(p, agent, renamed, status='active', description='New scope')
    assert reopened.verification_summary is None and not reopened.verification_report_ids
    assert p.requirements.manage_requirement(agent, 'p', 'get', parent.id)['status'] == 'active'


def test_draft_parent_only_allows_draft_children(app):
    p, _, _, agent, *_ = app
    parent = p.requirements.manage_requirement(agent, 'p', 'create', changes={'title': 'Planned', 'text': 'Planned scope', 'status': 'draft'})
    with pytest.raises(Conflict): p.workspaces.create_task(agent, 'p', parent.id, 'Start too soon')
    child = p.workspaces.create_task(agent, 'p', parent.id, 'Draft', initial_status='draft')
    with pytest.raises(Conflict): update(p, agent, child, status='active')
    current = p.requirements.manage_requirement(agent, 'p', 'get', parent.id)
    p.requirements.manage_requirement(agent, 'p', 'update', parent.id, current['version'], {'status': 'active'}, 'Start')
    assert update(p, agent, child, status='active').status == 'active'
