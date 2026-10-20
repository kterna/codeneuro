"""Previously fixed audit defects, re-expressed with Requirement → Task ownership."""
from datetime import datetime, timezone

import pytest

from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError
from test_product_core import app, update
from helpers import create_scope, file_query, propose_review, LEVELS


def test_d02_archived_task_blocks_draft_reactivation_and_restore_does_not_revive(app):
    p, uow, _, agent, task, parent, _ = app
    draft = p.governance.create_task_rule(agent, task.id, 'Draft', ('Point',), ('src/**',), 'Reason')['rule']
    stamp = datetime.now(timezone.utc).isoformat()
    report = p.governance.report_test(agent, task.id, 'one', ('pytest',), (), 0, stamp, stamp)
    archived = update(p, agent, task, archived=True)
    assert p.requirements.manage_requirement(agent, 'p', 'get', parent.id)['status'] == 'active'
    with uow.read() as tx: rule = tx.knowledge.get_rule(draft['id'])
    assert rule.status == 'deprecated'
    with pytest.raises(Conflict): p.governance.mutate_task_rule(agent, task.id, rule.id, rule.version, 'activate', 'Archived')
    update(p, agent, archived, archived=False)
    with pytest.raises(Conflict, match='Inactive'):
        p.governance.observe_rule(agent, task.id, rule.id, rule.version, report.id, True, 'Cannot revive')
    with pytest.raises(Conflict, match='not editable'):
        p.governance.mutate_task_rule(agent, task.id, rule.id, rule.version, 'activate', 'Cannot revive')


def test_d03_delete_populated_project_preserves_other_project(app):
    p, uow, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Rule', ('Point',), ('src/**',))
    delivery = p.context.get_context(agent, 'p', file_query(('src/file.py',)), 'del', task_id=task.id)
    p.feedback.rate_rule(agent, delivery.id, rule.id, 5, 'Useful')
    p.context.record_finding(agent, task.id, 'src/**', 'Note')
    propose_review(p, agent, task.id, rule.id, 'Proposed', ('Improved',), ('src/**',), Priority.P1, 'Reason')
    stamp = datetime.now(timezone.utc).isoformat()
    p.governance.report_test(agent, task.id, 'host-test', ('pytest',), (), 0, stamp, stamp)
    _, other = create_scope(p, agent, 'q')
    other_rule = p.knowledge.create_rule(human, 'q', 'Other rule', ('Point',), ('src/**',))
    assert p.workspaces.delete_project(human, 'p')['deleted']
    with uow.read() as tx:
        assert {item['id'] for item in tx.workspaces.list_projects()} == {'q'}
        assert tx.knowledge.get_rule(other_rule.id).title == 'Other rule'
        assert tx.workspaces.get_task(other.id, 'q') == other
        assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('identity', ['bad/project', '-bad', 'bad space', '', 'a' * 129])
def test_d17_project_id_validation(app, identity):
    p, _, human, *_ = app
    with pytest.raises(ProductError, match='Project ID'): p.workspaces.register_project(human, identity, 'Bad')
    with pytest.raises(Conflict, match='already exists'): p.workspaces.register_project(human, 'p', 'Duplicate')


def test_d20_audit_pagination(app):
    p, uow, human, *_ = app
    with uow.write() as tx:
        for number in range(110): tx.audit.record('p', 'tester', 'test.event', f'ent-{number}', {'i': number})
    first = p.ledger.events(human, 'p', limit=50)
    second = p.ledger.events(human, 'p', limit=50, before=first['next_cursor'])
    assert len(first['items']) == len(second['items']) == 50
    first_ids = {item['sequence'] for item in first['items']}
    second_ids = {item['sequence'] for item in second['items']}
    assert first_ids.isdisjoint(second_ids) and max(second_ids) < min(first_ids)


def test_d07_proposals_show_original_target_snapshot(app):
    p, _, human, agent, task, *_ = app
    target = p.knowledge.create_rule(human, 'p', 'Original Target', ('Original point',), ('src/core/**',))
    proposal = propose_review(p, agent, task.id, target.id, 'Proposed Title', ('New point',),
        ('src/core/**', 'src/api/**'), Priority.P0, 'Need stronger contract')
    row = p.ledger.project(human, 'p')['proposals'][0]
    assert row['id'] == proposal.id and row['target_version'] == row['current_target_version'] == 1
    assert row['target_snapshot']['title'] == 'Original Target' and row['target_snapshot']['priority'] == 'P1'
    assert row['priority'] == 'P0' and row['topics'] == ('test-contracts',) and row['task_id'] == task.id
    assert 'session_id' not in row


def test_d13_delivery_count_and_evaluation_count_are_distinct(app):
    p, _, human, agent, task, *_ = app
    rule = p.knowledge.create_rule(human, 'p', 'Global Rule', ('Point',), ('src/**',), Priority.P0)
    first = p.context.get_context(agent, 'p', file_query(('src/1.py',)), 'd1', task_id=task.id)
    p.context.get_context(agent, 'p', file_query(('src/1.py',)), 'd1', task_id=task.id)
    p.context.get_context(agent, 'p', file_query(('src/2.py',)), 'd2', task_id=task.id)
    p.feedback.rate_rule(agent, first.id, rule.id, 5, 'Useful')
    row = next(r for r in p.ledger.project(human, 'p')['rules'] if r['id'] == rule.id)
    assert row['delivery_count'] == 2 and row['eval_count'] == 1


def test_d04_d05_scope_tree_and_inspect_are_registered_patterns_only(app):
    p, _, human, _, task, *_ = app
    p.knowledge.create_rule(human, 'p', 'Core Rule', ('Point',), ('src/core/**',), Priority.P0)
    p.knowledge.create_rule(human, 'p', 'Pay Rule', ('Point',), ('src/pay/*.py',))
    tree = p.ledger.scope_tree(human, 'p')
    assert tree['source'] == 'registered_scopes' and tree['workspace'] is None
    assert {item['path'] for item in tree['tree']} == {'src/core/**', 'src/pay/*.py'}
    matching = p.ledger.inspect_path(human, 'p', 'src/pay/checkout.py', LEVELS, task.id)
    assert matching['source'] == 'jit_scope_match' and len(matching['rule_ids']) == 1
    assert not p.ledger.inspect_path(human, 'p', 'src/payment/checkout.py', LEVELS, task.id)['rule_ids']


def test_aggregate_counts_are_not_the_first_ledger_page(app):
    p, _, human, agent, task, parent, _ = app
    for number in range(25):
        p.requirements.manage_requirement(agent, 'p', 'create', changes={'title': f'Goal {number}', 'text': 'Scope'})
    for number in range(102): p.workspaces.create_task(agent, 'p', parent.id, f'Task {number}')
    ledger = p.ledger.project(human, 'p')
    assert len(ledger['requirements']) == 20 and ledger['requirements_next_cursor']
    assert len(ledger['tasks']) == 100 and ledger['tasks_next_cursor']
    assert ledger['counts']['requirements']['total'] == 26 and ledger['counts']['tasks']['total'] == 103
    rest = p.workspaces.manage_task(agent, 'p', 'list', cursor=ledger['tasks_next_cursor'])
    assert len(rest['items']) == 3
    assert p.requirements.manage_requirement(agent, 'p', 'get', parent.id)['progress']['total'] == 103
