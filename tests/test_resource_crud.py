"""Resource CRUD preserves history, scope and transactional lifecycle effects."""
import sqlite3

from alembic import command
import pytest
from sqlalchemy import text

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from test_product_core import app
from test_topics_v2 import config
from v2_helpers import file_query


def test_task_crud_updates_metadata_and_general_statuses(app):
    service, _, _, agent, task, _, _ = app
    changed = service.workspaces.manage_task(agent, 'p', 'update', task.id, task.revision,
        {'title': 'Revised task', 'description': 'More detail', 'status': 'testing'}, 'Clarify')
    assert changed.title == 'Revised task' and changed.description == 'More detail'
    assert changed.revision == task.revision + 1
    paused = service.workspaces.manage_task(agent, 'p', 'update', task.id, changed.revision,
                                            {'status': 'paused'}, 'Wait')
    assert paused.paused_from == 'testing'
    with pytest.raises(Conflict):
        service.workspaces.manage_task(agent, 'p', 'update', task.id, paused.revision,
                                      {'status': 'active'}, 'Cannot skip previous state')
    resumed = service.workspaces.manage_task(agent, 'p', 'update', task.id, paused.revision,
                                             {'status': 'testing'}, 'Continue')
    assert resumed.paused_from is None
    with pytest.raises(Conflict):
        service.workspaces.manage_task(agent, 'p', 'delete', task.id, task.revision, reason='Stale')
    with pytest.raises(ProductError, match='not found'):
        service.workspaces.manage_task(agent, 'q', 'get', task.id)


def test_requirement_revision_preserves_original_and_immutable_delivery(app):
    service, uow, _, agent, task, session, _ = app
    item = service.requirements.manage_requirement(agent, task.id, 'create',
        changes={'text': '  Original demand\n'}, request_id='original')
    query = file_query(('src/pay.py',))
    old = service.context.get_context(agent, session.id, query, 'original-delivery')
    revised = service.requirements.manage_requirement(agent, task.id, 'update', item.id, item.version,
                                                       {'text': 'Revised demand'}, 'New acceptance criteria')
    assert revised.version == 2
    with uow.read() as tx:
        row = tx.c.execute(text('SELECT original_text, current_text FROM requirements WHERE id=:id'),
                           {'id': item.id}).one()
        assert tuple(row) == ('  Original demand\n', 'Revised demand')
    assert service.context.get_context(agent, session.id, query, 'original-delivery') == old
    current = service.context.get_context(agent, session.id, query, 'revised-delivery')
    assert current.requirement_refs == ((item.id, 2),) and 'Revised demand' in current.markdown
    detail = service.requirements.manage_requirement(agent, task.id, 'get', item.id)
    assert [v['text'] for v in detail['history']] == [item.text, revised.text]
    retry = service.requirements.manage_requirement(agent, task.id, 'create',
        changes={'text': item.text}, request_id='original')
    assert retry == revised
    with pytest.raises(Conflict):
        service.requirements.manage_requirement(agent, task.id, 'update', item.id, 1,
                                                {'text': 'Stale text'}, 'Stale')
    other = service.workspaces.create_task(agent, 'q', 'Unrelated')
    with pytest.raises(ProductError, match='outside this Task'):
        service.requirements.manage_requirement(agent, other.id, 'get', item.id)
    with pytest.raises(ProductError, match='outside this Task'):
        service.requirements.manage_requirement(agent, other.id, 'delete', item.id, 2, reason='Wrong Task')


def test_requirement_soft_delete_preserves_references_without_completing_task(app):
    service, uow, human, agent, task, session, _ = app
    item = service.requirements.manage_requirement(agent, task.id, 'create', changes={'text': 'Withdraw this'})
    rule = service.knowledge.create_rule(human, 'p', 'Linked', ('Constraint',), ('src/**',), task_id=task.id)
    with uow.write() as tx:
        tx.requirements.link_rule(item.id, rule.id)
    query = file_query(('src/pay.py',))
    old = service.context.get_context(agent, session.id, query, 'before-delete')
    deleted = service.requirements.manage_requirement(agent, task.id, 'delete', item.id, 1, reason='Withdrawn')
    assert deleted.status == 'deleted' and deleted.version == 2
    assert service.requirements.manage_requirement(agent, task.id, 'list') == []
    assert service.workspaces.manage_task(agent, 'p', 'get', task.id).status == 'active'
    detail = service.requirements.manage_requirement(agent, task.id, 'get', item.id)
    assert [v['status'] for v in detail['history']] == ['active', 'deleted']
    assert service.context.get_context(agent, session.id, query, 'before-delete') == old
    after = service.context.get_context(agent, session.id, query, 'after-delete')
    assert not after.requirement_refs and not after.rule_refs
    with uow.read() as tx:
        assert tx.knowledge.get_rule(rule.id).status == 'deprecated'
        assert tx.c.execute(text('SELECT count(*) FROM requirement_rule_links')).scalar_one() == 1
        assert tx.c.execute(text('SELECT count(*) FROM delivery_requirements')).scalar_one() == 1
    with pytest.raises(Conflict):
        service.requirements.archive_requirement(agent, session.id, item.id, 2, 'Not completion')
    with pytest.raises(Conflict):
        service.requirements.manage_requirement(agent, task.id, 'update', item.id, 2,
                                                {'status': 'active'}, 'Deleted record')


def test_task_soft_delete_hides_owned_context_without_erasing_children(app):
    service, uow, human, agent, task, session, _ = app
    item = service.requirements.manage_requirement(agent, task.id, 'create', changes={'text': 'Owned demand'})
    local = service.knowledge.create_rule(human, 'p', 'Local', ('Task rule',), ('src/**',), task_id=task.id)
    shared = service.knowledge.create_rule(human, 'p', 'Shared', ('Project rule',), ('src/**',))
    service.context.record_finding(agent, session.id, 'src/**', 'Owned finding')
    query = file_query(('src/pay.py',))
    old = service.context.get_context(agent, session.id, query, 'before-delete')
    current = service.workspaces.manage_task(agent, 'p', 'get', task.id)
    deleted = service.workspaces.manage_task(agent, 'p', 'delete', task.id, current.revision, reason='Withdraw task')
    assert deleted.status == 'deleted'
    assert service.workspaces.list_tasks(agent, 'p') == []
    assert service.requirements.manage_requirement(agent, task.id, 'list') == []
    assert service.requirements.manage_requirement(agent, task.id, 'get', item.id)['text'] == item.text
    ledger = service.ledger.project(human, 'p')
    assert not ledger['tasks'] and not ledger['requirements']
    after = service.context.get_context(agent, session.id, query, 'after-delete')
    assert not after.requirement_refs and not after.finding_refs
    assert shared.id in after.markdown and local.id not in after.markdown
    assert service.context.get_context(agent, session.id, query, 'before-delete') == old
    with uow.read() as tx:
        assert tx.requirements.get_requirement(item.id, task.id).status == 'active'
        assert tx.c.execute(text('PRAGMA foreign_key_check')).all() == []
    with pytest.raises(Conflict):
        service.workspaces.start_session(agent, 'p', 'other', task.id)
    with pytest.raises(Conflict):
        service.requirements.manage_requirement(agent, task.id, 'create', changes={'text': 'Blocked'})


@pytest.mark.parametrize('event', ['task.updated', 'task.deleted', 'requirement.updated', 'requirement.deleted'])
def test_crud_audit_failure_rolls_back_data_and_snapshots(app, event):
    service, uow, _, agent, task, _, _ = app
    item = service.requirements.manage_requirement(agent, task.id, 'create', changes={'text': 'Original'})
    before_task = service.workspaces.manage_task(agent, 'p', 'get', task.id)
    with uow.write() as tx:
        tx.c.execute(text(f"CREATE TRIGGER reject_crud BEFORE INSERT ON audit WHEN NEW.action='{event}' "
                          "BEGIN SELECT RAISE(ABORT,'injected failure'); END"))
    with pytest.raises(Exception, match='injected failure'):
        if event.startswith('task.'):
            service.workspaces.manage_task(agent, 'p', 'delete' if event.endswith('deleted') else 'update',
                task.id, before_task.revision, None if event.endswith('deleted') else {'title': 'Changed'}, 'Change')
        else:
            service.requirements.manage_requirement(agent, task.id, 'delete' if event.endswith('deleted') else 'update',
                item.id, item.version, None if event.endswith('deleted') else {'text': 'Changed'}, 'Change')
    assert service.workspaces.manage_task(agent, 'p', 'get', task.id) == before_task
    detail = service.requirements.manage_requirement(agent, task.id, 'get', item.id)
    assert detail['text'] == 'Original' and detail['status'] == 'active' and len(detail['history']) == 1


def test_upgrade_existing_tasks_requirements_and_history(tmp_path):
    filename = tmp_path / 'previous.db'
    command.upgrade(config(filename), '2c4e8a6b901d')
    with sqlite3.connect(filename) as db:
        db.execute("INSERT INTO projects(id,name) VALUES('p','Existing')")
        db.execute("INSERT INTO tasks(id,project_id,title,status,revision) VALUES('t','p','Existing','archived',2)")
        db.execute("INSERT INTO requirements(id,project_id,task_id,original_text,status,version,completion_summary) "
                   "VALUES('r','p','t','Original','archived',2,'Previously complete')")
        db.execute("INSERT INTO requirement_versions VALUES('r',1,'Original','active',NULL)")
        db.execute("INSERT INTO requirement_versions VALUES('r',2,'Original','archived','Previously complete')")
    command.upgrade(config(filename), 'head')
    uow = SqliteUnitOfWork(str(filename))
    try:
        product, agent = Product(uow), Actor('agent')
        current = product.workspaces.manage_task(agent, 'p', 'get', 't')
        assert current.status == 'archived' and current.revision == 2
        detail = product.requirements.manage_requirement(agent, 't', 'get', 'r')
        assert detail['text'] == 'Original' and detail['summary'] == 'Previously complete'
        assert len(detail['history']) == 2
        product.workspaces.manage_task(agent, 'p', 'update', 't', 2, {'status': 'active'}, 'Continue')
        product.requirements.manage_requirement(agent, 't', 'update', 'r', 2,
            {'status': 'active', 'text': 'Revised'}, 'Continue with revised scope')
        product.requirements.manage_requirement(agent, 't', 'delete', 'r', 3, reason='Withdrawn')
        with uow.read() as tx:
            row = tx.c.execute(text('SELECT original_text,current_text,status FROM requirements')).one()
            assert tuple(row) == ('Original', 'Revised', 'deleted')
            assert tx.c.execute(text('PRAGMA foreign_key_check')).all() == []
    finally:
        uow.dispose()
