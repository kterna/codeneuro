"""Regression tests verifying fixes for D01-D32 audit defects."""
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import text

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError, TaskStatus
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from scripts.load_batches_into_codeneuro import load_and_validate, ingest_batches


@pytest.fixture
def app(tmp_path):
    filename = str(tmp_path / 'audit_test.db')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro',
                    'migrate', '--db', filename],
                   cwd=root, capture_output=True, text=True, check=True)
    uow = SqliteUnitOfWork(filename)
    service = Product(uow)
    human = Actor('human', 'human')
    agent = Actor('agent')
    service.workspaces.register_project(human, 'proj-a', 'Primary Project')
    service.workspaces.register_project(human, 'proj-b', 'Secondary Project')
    yield service, uow, human, agent, filename
    uow.dispose()


def test_d02_archived_requirement_blocks_draft_reactivation(app):
    service, uow, human, agent, _ = app
    task = service.workspaces.create_task(agent, 'proj-a', 'Task multi-req')
    sess = service.workspaces.start_session(agent, 'proj-a', 'wt', task.id, debug=True)

    r1 = service.requirements.submit_requirement(agent, sess.id, 'Req 1', 'req-1')
    r2 = service.requirements.submit_requirement(agent, sess.id, 'Req 2', 'req-2')

    draft = service.governance.create_task_rule(
        agent, sess.id, 'Rule for Req 1', ('Point 1',), ('src/**',),
        'Reason', Priority.P1, 'business', requirement_id=r1.id
    )
    rule_id = draft['rule']['id']

    # Archive Req 1 (Task stays active because of Req 2)
    service.requirements.archive_requirement(agent, sess.id, r1.id, 1, 'R1 done')
    with uow.read() as tx:
        assert tx.workspaces.get_task(task.id, 'proj-a').status == TaskStatus.ACTIVE

    # After requirement is archived, linked draft rule is deprecated and cannot be observed or reactivated
    with uow.read() as tx:
        cur_rule = tx.knowledge.get_rule(rule_id)
        assert cur_rule.status == 'deprecated'

    now = datetime.now(timezone.utc).isoformat()
    t1 = service.governance.report_test(agent, sess.id, 'req-t1', ('pytest',), ('src/a.py',), 0, now, now)

    with pytest.raises(Conflict, match='linked Requirement is archived'):
        service.governance.observe_rule(agent, sess.id, rule_id, cur_rule.version, t1.id, True, 'ok')

    with pytest.raises(Conflict, match='linked Requirement is archived'):
        service.governance.mutate_task_rule(agent, sess.id, rule_id, cur_rule.version, 'activate', 'try activating')


def test_d03_delete_populated_project(app):
    service, uow, human, agent, _ = app
    task_a = service.workspaces.create_task(agent, 'proj-a', 'Task A')
    sess_a = service.workspaces.start_session(agent, 'proj-a', 'wt-a', task_a.id, debug=True)
    req_a = service.requirements.submit_requirement(agent, sess_a.id, 'Requirement A', 'req-a')
    rule_a = service.knowledge.create_rule(human, 'proj-a', 'Rule A', ('P',), ('src/**',), Priority.P1)
    # Deliver context & add feedback
    delivery = service.context.get_context(agent, sess_a.id, ContextQuery(('src/file.py',)), 'req-del-a')
    service.feedback.rate_rule(agent, sess_a.id, delivery.id, rule_a.id, 5, 'Great rule')
    service.context.record_finding(agent, sess_a.id, 'src/**', 'Note', Priority.P1)
    service.knowledge.propose_contract(agent, sess_a.id, rule_a.id, 'Rule A proposed',
                                       ('P',), ('src/**',), Priority.P1, 'business', 'reason')

    # Data in project B
    task_b = service.workspaces.create_task(agent, 'proj-b', 'Task B')
    sess_b = service.workspaces.start_session(agent, 'proj-b', 'wt-b', task_b.id, debug=True)
    rule_b = service.knowledge.create_rule(human, 'proj-b', 'Rule B', ('P',), ('src/**',), Priority.P0)

    # Delete project A
    del_res = service.workspaces.delete_project(human, 'proj-a')
    assert del_res['deleted'] is True

    with uow.read() as tx:
        # Project A is gone
        assert not any(p['id'] == 'proj-a' for p in tx.workspaces.list_projects())
        # Project B is intact
        assert any(p['id'] == 'proj-b' for p in tx.workspaces.list_projects())
        assert tx.knowledge.get_rule(rule_b.id).title == 'Rule B'


def test_d17_project_id_validation_and_conflict(app):
    service, _, human, _, _ = app
    # Invalid IDs with slashes, spaces or illegal characters
    with pytest.raises(ProductError, match='Project ID must start with a letter'):
        service.workspaces.register_project(human, 'bad/project', 'Bad')
    with pytest.raises(ProductError, match='Project ID must start with a letter'):
        service.workspaces.register_project(human, '-bad', 'Bad')
    with pytest.raises(ProductError, match='Project ID must start with a letter'):
        service.workspaces.register_project(human, 'bad space', 'Bad')

    # Duplicate project ID returns Conflict
    with pytest.raises(Conflict, match='already exists'):
        service.workspaces.register_project(human, 'proj-a', 'Duplicate')


def test_d20_audit_pagination(app):
    service, uow, human, agent, _ = app
    # Generate 110 audit events in proj-a
    with uow.write() as tx:
        for i in range(110):
            tx.audit.record('proj-a', 'tester', 'test.event', f'ent-{i}', {'i': i})

    page1 = service.ledger.events(human, 'proj-a', limit=50)
    assert len(page1['items']) == 50
    assert page1['next_cursor'] is not None

    page2 = service.ledger.events(human, 'proj-a', limit=50, before=page1['next_cursor'])
    assert len(page2['items']) == 50
    assert page2['next_cursor'] is not None
    # No duplicate sequences across pages
    seq1 = {item['sequence'] for item in page1['items']}
    seq2 = {item['sequence'] for item in page2['items']}
    assert seq1.isdisjoint(seq2)
    assert max(seq2) < min(seq1)


def test_d22_task_transitions_and_rules_deprecation(app):
    service, uow, human, agent, _ = app
    # Create draft task
    task = service.workspaces.create_task(agent, 'proj-a', 'Draft Task', initial_status='draft')
    assert task.status == TaskStatus.DRAFT

    # draft -> active
    t_act = service.workspaces.transition_task(human, 'proj-a', task.id, 0, 'active', 'Start work')
    assert t_act.status == TaskStatus.ACTIVE

    # active -> testing
    t_test = service.workspaces.transition_task(human, 'proj-a', task.id, t_act.revision, 'testing', 'Begin QA')
    assert t_test.status == TaskStatus.TESTING

    # testing -> released fails if there are active requirements
    sess = service.workspaces.start_session(agent, 'proj-a', 'wt', task.id, debug=True)
    req = service.requirements.submit_requirement(agent, sess.id, 'Must pass QA', 'req-qa')
    task_rule = service.knowledge.create_rule(human, 'proj-a', 'QA Rule', ('P',), ('src/**',), task_id=task.id)

    with uow.read() as tx:
        cur_task = tx.workspaces.get_task(task.id, 'proj-a')

    with pytest.raises(Conflict, match='Archive the active Requirements'):
        service.workspaces.transition_task(human, 'proj-a', task.id, cur_task.revision, 'released', 'Ship')

    # Archive the requirement in task, which automatically archives the task per contract
    service.requirements.archive_requirement(agent, sess.id, req.id, 1, 'Passed QA')
    with uow.read() as tx:
        auto_archived_task = tx.workspaces.get_task(task.id, 'proj-a')
        assert auto_archived_task.status == TaskStatus.ARCHIVED

    # Human can now explicitly transition archived -> released (D22 completion flow)
    t_released = service.workspaces.transition_task(
        human, 'proj-a', task.id, auto_archived_task.revision, 'released', 'Ship archived task to production'
    )
    assert t_released.status == TaskStatus.RELEASED

    # Create a zero-requirement task to test testing -> released -> archived flow (D22)
    zero_task = service.workspaces.create_task(agent, 'proj-a', 'Zero Req Task')
    z_rule = service.knowledge.create_rule(human, 'proj-a', 'Z Rule', ('P',), ('src/**',), task_id=zero_task.id)
    with uow.read() as tx:
        zero_task = tx.workspaces.get_task(zero_task.id, 'proj-a')
    z_test = service.workspaces.transition_task(human, 'proj-a', zero_task.id, zero_task.revision, 'testing', 'Testing zero-req')
    z_rel = service.workspaces.transition_task(human, 'proj-a', zero_task.id, z_test.revision, 'released', 'Ship zero-req')
    assert z_rel.status == TaskStatus.RELEASED

    # Task rule deprecated on task release
    with uow.read() as tx:
        assert tx.knowledge.get_rule(z_rule.id).status == 'deprecated'

    z_arch = service.workspaces.transition_task(human, 'proj-a', zero_task.id, z_rel.revision, 'archived', 'Archive zero-req')
    assert z_arch.status == TaskStatus.ARCHIVED


def test_d07_proposals_snapshot_and_version(app):
    service, uow, human, agent, _ = app
    task = service.workspaces.create_task(agent, 'proj-a', 'Task for proposal')
    sess = service.workspaces.start_session(agent, 'proj-a', 'wt', task.id, debug=True)
    target = service.knowledge.create_rule(human, 'proj-a', 'Original Target', ('Orig point',),
                                          ('src/core/**',), Priority.P1, 'business')

    service.knowledge.propose_contract(
        agent, sess.id, target.id, 'Proposed Title', ('New point',),
        ('src/core/**', 'src/api/**'), Priority.P0, 'security', 'Need P0 security'
    )

    ledger_data = service.ledger.project(human, 'proj-a')
    proposals = ledger_data['proposals']
    assert len(proposals) == 1
    p = proposals[0]
    assert p['target_version'] == 1
    assert p['current_target_version'] == 1
    assert p['target_snapshot']['title'] == 'Original Target'
    assert p['target_snapshot']['priority'] == 'P1'
    assert p['priority'] == 'P0'
    assert p['category'] == 'security'


def test_d13_delivery_count_vs_eval_count(app):
    service, uow, human, agent, _ = app
    task = service.workspaces.create_task(agent, 'proj-a', 'Task')
    sess = service.workspaces.start_session(agent, 'proj-a', 'wt', task.id, debug=True)
    rule = service.knowledge.create_rule(human, 'proj-a', 'Global Rule', ('P',), ('src/**',), Priority.P0)

    # Deliver twice
    d1 = service.context.get_context(agent, sess.id, ContextQuery(('src/1.py',)), 'req-d1')
    d2 = service.context.get_context(agent, sess.id, ContextQuery(('src/2.py',)), 'req-d2')

    # Rate once
    service.feedback.rate_rule(agent, sess.id, d1.id, rule.id, 5, 'Good')

    ledger = service.ledger.project(human, 'proj-a')
    rule_data = next(r for r in ledger['rules'] if r['id'] == rule.id)
    assert rule_data['delivery_count'] == 2
    assert rule_data['eval_count'] == 1


def test_d04_d05_scope_tree_and_inspect_path(app):
    service, _, human, agent, _ = app
    task = service.workspaces.create_task(agent, 'proj-a', 'Task')
    service.knowledge.create_rule(human, 'proj-a', 'Core Rule', ('P',), ('src/core/**',), Priority.P0)
    service.knowledge.create_rule(human, 'proj-a', 'Pay Rule', ('P',), ('src/pay/*.py',), Priority.P1)

    # scope_tree returns registered scopes
    tree_res = service.ledger.scope_tree(human, 'proj-a')
    assert tree_res['source'] == 'registered_scopes'
    paths = [item['path'] for item in tree_res['tree']]
    assert 'src/core/**' in paths
    assert 'src/pay/*.py' in paths

    # inspect_path tests anchored match
    inspect_match = service.ledger.inspect_path(human, 'proj-a', 'src/pay/checkout.py', task.id)
    assert inspect_match['source'] == 'jit_scope_match'
    assert len(inspect_match['rule_ids']) == 1

    # payment is not pay
    inspect_non_match = service.ledger.inspect_path(human, 'proj-a', 'src/payment/checkout.py', task.id)
    assert len(inspect_non_match['rule_ids']) == 0


def test_d31_d32_batch_importer_validation_and_invariants(tmp_path):
    db_file = str(tmp_path / 'import_target.db')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-B', '-m', 'codeneuro', 'migrate', '--db', db_file],
                   cwd=root, capture_output=True, text=True, check=True)

    # 1. Invalid batch with unknown project reference should raise
    invalid_batch = {
        'tasks': [{'id': 'task-1', 'project_id': 'nonexistent-proj', 'title': 'T'}]
    }
    inv_file = tmp_path / 'invalid.json'
    inv_file.write_text(json.dumps(invalid_batch), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown project_id'):
        load_and_validate([str(inv_file)])

    # 2. Valid batch
    valid_batch = {
        'projects': [{'id': 'proj-imp', 'name': 'Imported Project'}],
        'tasks': [{
            'id': 'task-imp', 'project_id': 'proj-imp', 'title': 'Task Imp',
            'requirements': [{'id': 'req-imp', 'text': 'Requirement text', 'status': 'active'}]
        }],
        'rules': [{
            'id': 'rule-imp', 'project_id': 'proj-imp', 'task_id': 'task-imp',
            'title': 'Rule Imp', 'points': ['Pt 1'], 'patterns': ['src/**'],
            'priority': 'P1', 'category': 'business', 'status': 'active'
        }]
    }
    val_file = tmp_path / 'valid.json'
    val_file.write_text(json.dumps(valid_batch), encoding='utf-8')

    parsed = load_and_validate([str(val_file)])
    ingest_batches(parsed, db_file, dry_run=False)

    # Verify rule_versions, requirement_versions, audit, and JIT delivery work
    uow = SqliteUnitOfWork(db_file)
    with uow.read() as tx:
        rv_count = tx.c.execute(text("SELECT count(*) FROM rule_versions")).scalar_one()
        reqv_count = tx.c.execute(text("SELECT count(*) FROM requirement_versions")).scalar_one()
        audit_count = tx.c.execute(text("SELECT count(*) FROM audit")).scalar_one()
        assert rv_count == 1
        assert reqv_count == 1
        assert audit_count >= 3

    # Verify JIT context delivery works seamlessly (no IntegrityError on rule_versions)
    service = Product(uow)
    agent = Actor('agent')
    sess = service.workspaces.start_session(agent, 'proj-imp', 'wt', 'task-imp', debug=True)
    delivery = service.context.get_context(agent, sess.id, ContextQuery(('src/main.py',)), 'del-imp')
    assert 'Rule Imp' in delivery.markdown
    uow.dispose()
