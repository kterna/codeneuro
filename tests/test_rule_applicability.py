"""Rule delivery modes: one-line cards, recorded openings and the one-time migration."""
from datetime import datetime, timedelta, timezone
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.tasks import Conflict, ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from helpers import REVIEW, configure_fixture, create_scope, file_query, initialize_database

ROOT = Path(__file__).resolve().parents[1]
APPLICABILITY_CHANGES = [
    pytest.param(('full', ''), {'delivery_mode': 'card', 'applies_when': '准备提交时'},
                 ('card', '准备提交时'), id='full-to-card'),
    pytest.param(('card', '准备提交时'), {'delivery_mode': 'full', 'applies_when': ''},
                 ('full', ''), id='card-to-full'),
    pytest.param(('card', '准备提交时'), {'applies_when': '准备推送时'},
                 ('card', '准备推送时'), id='change-trigger'),
]


@pytest.fixture
def app(tmp_path):
    filename = str(tmp_path / 'product.db')
    initialize_database(filename)
    uow = SqliteUnitOfWork(filename)
    product = Product(uow)
    human, agent = Actor('owner', 'human'), Actor('agent')
    product.workspaces.register_project(human, 'p', 'p')
    configure_fixture(product, human, ('p',))
    _, task = create_scope(product, agent)
    yield product, uow, human, agent, task
    uow.dispose()


def test_card_rules_stay_one_line_and_full_rules_keep_text(app):
    p, _, human, agent, task = app
    full = p.knowledge.create_rule(human, 'p', 'Always', ('Read the file first',), ('src/**',), Priority.P1)
    card = p.knowledge.create_rule(human, 'p', 'Commit guard', ('Never stage local config',), ('src/**',),
                                   Priority.P0, delivery_mode='card', applies_when='准备 commit、merge 或 push 时')
    delivered = p.context.get_context(agent, 'p', file_query(('src/main.py',)), 'cards', task_id=task.id)
    assert 'Read the file first' in delivered.markdown
    assert 'Never stage local config' not in delivered.markdown
    assert f'- {card.priority} {card.id}@{card.version} Commit guard — 准备 commit、merge 或 push 时' in delivered.markdown
    assert (full.id, 1, 'full') in delivered.rule_refs and (card.id, 1, 'card') in delivered.rule_refs
    listed = [item for item in delivered.sections['applicable_cards'] if item['id'] == card.id]
    assert listed and listed[0]['applies_when'].startswith('准备')


def test_cards_survive_a_tight_text_budget(app):
    p, _, human, agent, task = app
    card = p.knowledge.create_rule(human, 'p', 'Commit guard', ('Never stage local config',), ('src/**',),
                                   delivery_mode='card', applies_when='准备提交时')
    filler = p.knowledge.create_rule(human, 'p', 'Long', ('FILL' * 400,), ('src/**',), Priority.P2)
    delivered = p.context.get_context(agent, 'p', file_query(('src/main.py',), max_chars=512), 'tight',
                                      task_id=task.id)
    assert card.id in delivered.markdown and f'Omitted rules: {filler.id}' in delivered.markdown
    assert filler.id not in [ref[0] for ref in delivered.rule_refs]
    assert not delivered.budget_exceeded


def test_large_directory_keeps_every_card_without_loading_bodies(app):
    p, uow, human, agent, _ = app
    cards = [p.knowledge.create_rule(human, 'p', f'Action {number:02d} ' + 'Applicable operation ' * 12,
        (f'Body loaded only on demand {number:02d}',), ('src/**',), delivery_mode='card',
        applies_when=f'准备执行操作 {number:02d} 时') for number in range(40)]
    query = file_query(('src/main.py',), priorities=(Priority.P1,), max_chars=512)
    delivered = p.context.get_context(agent, 'p', query, 'large-directory')
    directory_lines = [line for line in delivered.markdown.splitlines() if line.startswith('- P1 ')]
    assert len('\n'.join(directory_lines)) > 8000 and len(directory_lines) == len(cards)
    assert not delivered.omitted_rule_ids and not delivered.budget_exceeded
    assert set(delivered.rule_refs) == {(rule.id, rule.version, 'card') for rule in cards}
    assert len(delivered.sections['applicable_cards']) == len(cards)
    for rule in cards:
        assert f'{rule.id}@{rule.version} {rule.title.strip()} — {rule.applies_when}' in delivered.markdown
        assert rule.points[0] not in delivered.markdown
    historical = p.context.get_delivery(agent, delivered.id)
    with uow.read() as tx:
        assert not tx.context.delivery_selections(delivered.id)
        assert len(tx.context.delivery_rule_refs(delivered.id)) == len(cards)
    ordered = sorted(cards, key=lambda rule: rule.id)
    selected = (ordered[0], ordered[-1])
    opened = p.context.open_rules(agent, delivered.id, [rule.id for rule in selected], 'Read only relevant entries')
    assert [item['id'] for item in opened['rules']] == [rule.id for rule in selected]
    for item, rule in zip(opened['rules'], selected):
        assert item['version'] == rule.version and rule.points[0] in item['markdown']
    with uow.read() as tx:
        assert {item['rule_id'] for item in tx.context.delivery_selections(delivered.id)} == {rule.id for rule in selected}
    assert p.context.get_delivery(agent, delivered.id) == historical
    assert p.context.get_context(agent, 'p', query, 'large-directory') == delivered


def test_directory_keeps_full_text_p0_budget_overflow_visible(app):
    p, _, human, agent, _ = app
    guard = p.knowledge.create_rule(human, 'p', 'Critical guard', ('CRITICAL' * 160,), ('src/**',), Priority.P0)
    card = p.knowledge.create_rule(human, 'p', 'Commit guard', ('Commit-only body',), ('src/**',),
        delivery_mode='card', applies_when='准备提交时')
    delivered = p.context.get_context(agent, 'p', file_query(('src/main.py',), max_chars=512))
    assert delivered.budget_exceeded and guard.points[0] in delivered.markdown
    assert (guard.id, guard.version, 'full') in delivered.rule_refs
    assert (card.id, card.version, 'card') in delivered.rule_refs
    assert card.points[0] not in delivered.markdown


def test_rule_delivery_mode_validation():
    from codeneuro.modules.knowledge import Rule, validate_rule
    base = dict(id='rule_x', project_id='p', task_id=None, title='T', points=('P',),
                patterns=('src/**',), priority=Priority.P1, topics=('t',), version=1, status='active')
    with pytest.raises(ProductError):
        validate_rule(Rule(**base, delivery_mode='card'))
    with pytest.raises(ProductError):
        validate_rule(Rule(**base, delivery_mode='card', applies_when='准' * 61))
    with pytest.raises(ProductError):
        validate_rule(Rule(**base, applies_when='准备提交时'))
    with pytest.raises(ProductError):
        validate_rule(Rule(**base, is_global=True, delivery_mode='card', applies_when='准备提交时',
                           priority_reason='Global red line'))


def test_situation_is_recorded_without_changing_selection(app):
    p, _, human, agent, task = app
    rule = p.knowledge.create_rule(human, 'p', 'Always', ('Read it',), ('src/**',))
    plain = p.context.get_context(agent, 'p', file_query(('src/main.py',)), 'plain', task_id=task.id)
    stated = p.context.get_context(agent, 'p', file_query(('src/main.py',), situation='  准备   提交  '),
                                   'stated', task_id=task.id)
    assert stated.query['situation'] == '准备 提交'
    assert 'Situation: 准备 提交' in stated.markdown
    assert [ref[:2] for ref in plain.rule_refs] == [ref[:2] for ref in stated.rule_refs] == [(rule.id, 1)]


def test_open_rules_returns_the_recorded_version_and_keeps_one_selection(app):
    p, _, human, agent, task = app
    card = p.knowledge.create_rule(human, 'p', 'Commit guard', ('Never stage local config',), ('src/**',),
                                   delivery_mode='card', applies_when='准备提交时')
    delivered = p.context.get_context(agent, 'p', file_query(('src/main.py',)), 'open', task_id=task.id)
    with pytest.raises(ProductError):
        p.context.open_rules(agent, delivered.id, [card.id], '   ')
    opened = p.context.open_rules(agent, delivered.id, [card.id], '准备提交，先确认改动范围')
    assert opened['rules'][0]['markdown'].startswith('[P1] Commit guard (rule_')
    assert 'Never stage local config' in opened['rules'][0]['markdown']
    revised = p.knowledge.set_rule_applicability(human, 'p', card.id, card.version, 'card',
                                                 '准备推送时', '调整适用时机')
    assert revised.version == card.version + 1
    again = p.context.open_rules(agent, delivered.id, [card.id], '再次确认')
    assert again['rules'][0]['version'] == card.version
    assert again['rules'][0]['markdown'] == opened['rules'][0]['markdown']
    assert again['rules'][0]['applies_when'] == '准备提交时'
    with p.workspaces.uow.read() as tx:
        selected = tx.context.delivery_selections(delivered.id)
    assert [row['rule_id'] for row in selected] == [card.id] and selected[0]['version'] == card.version


def test_open_rules_rejects_foreign_or_already_full_rules(app):
    p, _, human, agent, task = app
    full = p.knowledge.create_rule(human, 'p', 'Always', ('Read it',), ('src/**',))
    delivered = p.context.get_context(agent, 'p', file_query(('src/main.py',)), 'foreign', task_id=task.id)
    assert p.context.open_rules(agent, delivered.id, [full.id], 'already delivered')['already_full'] == [full.id]
    with pytest.raises(ProductError) as missing:
        p.context.open_rules(agent, delivered.id, ['rule_absent'], 'unknown')
    assert missing.value.code == 'not_found'


def test_applicability_edit_requires_current_version(app):
    p, _, human, agent, task = app
    card = p.knowledge.create_rule(human, 'p', 'Guard', ('Clause',), ('src/**',),
                                   delivery_mode='card', applies_when='准备提交时')
    with pytest.raises(Conflict):
        p.knowledge.set_rule_applicability(human, 'p', card.id, card.version + 1, 'full', '', '过期版本')
    with pytest.raises(ProductError):
        p.knowledge.set_rule_applicability(agent, 'p', card.id, card.version, 'full', '', 'Agent 不能改')
    same = p.knowledge.set_rule_applicability(human, 'p', card.id, card.version, 'card', '准备提交时', '无变化')
    assert same.version == card.version


@pytest.mark.parametrize('before,changes,after', APPLICABILITY_CHANGES)
def test_reviewed_applicability_change_requires_review_before_promotion(app, before, changes, after):
    p, uow, human, agent, task = app
    draft = p.governance.create_task_rule(agent, task.id, 'Commit guard', ('Check the change scope',),
        ('src/**',), 'Synthetic review candidate', validation_spec=REVIEW,
        delivery_mode=before[0], applies_when=before[1])['rule']
    active = p.governance.review_task_rule(human, 'p', draft['id'], draft['version'], True,
                                          'Reviewed the original delivery behavior')
    updated = p.governance.mutate_task_rule(agent, task.id, active.id, active.version, 'update',
                                           'Change delivery behavior', **changes)
    changed = updated['rule']
    assert changed['version'] == active.version + 1 and changed['status'] == 'draft'
    assert (changed['delivery_mode'], changed['applies_when']) == after
    assert changed['points'] == active.points and changed['patterns'] == active.patterns
    assert updated['governance']['evidence_version'] == changed['version']
    with pytest.raises(Conflict, match='no longer active'):
        p.knowledge.promote_rule(agent, task.id, changed['id'], changed['version'], 'Reusable')
    with uow.read() as tx:
        original = tx.knowledge.rule_snapshot(active.id, active.version)
        assert (original['delivery_mode'], original['applies_when']) == before
        assert original['status'] == 'active'
    reviewed = p.governance.review_task_rule(human, 'p', changed['id'], changed['version'], True,
                                            'Reviewed the new delivery behavior')
    promoted = p.knowledge.promote_rule(agent, task.id, reviewed.id, reviewed.version, 'Reusable')
    assert promoted.task_id is None and promoted.status == 'active'
    assert (promoted.delivery_mode, promoted.applies_when) == after


def report_synthetic_support(product, agent, task_id, rule, batch):
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    for number in range(2):
        stamp = (start + timedelta(seconds=number)).isoformat()
        report = product.governance.report_test(agent, task_id, f'{batch}-{number}',
            ('fixture-test', batch, str(number)), (), 0, stamp, stamp)
        product.governance.observe_rule(agent, task_id, rule['id'], rule['version'], report.id,
                                        True, 'Synthetic passing evidence')


@pytest.mark.parametrize('before,changes,after', APPLICABILITY_CHANGES)
def test_tested_applicability_change_requires_new_evidence(app, before, changes, after):
    p, uow, _, agent, task = app
    draft = p.governance.create_task_rule(agent, task.id, 'Commit guard', ('Check the change scope',),
        ('src/**',), 'Synthetic test candidate', delivery_mode=before[0], applies_when=before[1])['rule']
    report_synthetic_support(p, agent, task.id, draft, 'original')
    active = p.governance.mutate_task_rule(agent, task.id, draft['id'], draft['version'], 'activate',
                                          'Original evidence is sufficient')['rule']
    updated = p.governance.mutate_task_rule(agent, task.id, active['id'], active['version'], 'update',
                                           'Change delivery behavior', **changes)
    changed = updated['rule']
    assert changed['version'] == active['version'] + 1 and changed['status'] == 'draft'
    assert (changed['delivery_mode'], changed['applies_when']) == after
    assert updated['governance']['evidence_version'] == changed['version']
    assert updated['governance']['support_count'] == 0
    with uow.read() as tx:
        assert len(tx.governance.observations(draft['id'], draft['version'])) == 2
    with pytest.raises(Conflict, match='two distinct'):
        p.governance.mutate_task_rule(agent, task.id, changed['id'], changed['version'], 'activate',
                                      'Old evidence must not activate changed behavior')
    with pytest.raises(Conflict, match='no longer active'):
        p.knowledge.promote_rule(agent, task.id, changed['id'], changed['version'], 'Reusable')
    report_synthetic_support(p, agent, task.id, changed, 'revised')
    reactivated = p.governance.mutate_task_rule(agent, task.id, changed['id'], changed['version'],
                                               'activate', 'New evidence is sufficient')['rule']
    promoted = p.knowledge.promote_rule(agent, task.id, reactivated['id'], reactivated['version'], 'Reusable')
    assert promoted.task_id is None and promoted.status == 'active'
    assert (promoted.delivery_mode, promoted.applies_when) == after


@pytest.mark.parametrize('delivery_mode,applies_when', [('full', ''), ('card', '准备提交时')])
def test_unchanged_applicability_keeps_activation_and_evidence(app, delivery_mode, applies_when):
    p, uow, _, agent, task = app
    draft = p.governance.create_task_rule(agent, task.id, 'Commit guard', ('Check the change scope',),
        ('src/**',), 'Synthetic test candidate', delivery_mode=delivery_mode, applies_when=applies_when)['rule']
    report_synthetic_support(p, agent, task.id, draft, 'original')
    active = p.governance.mutate_task_rule(agent, task.id, draft['id'], draft['version'], 'activate',
                                          'Original evidence is sufficient')['rule']
    with uow.read() as tx:
        original_state = tx.governance.state(active['id'])
    updated = p.governance.mutate_task_rule(agent, task.id, active['id'], active['version'], 'update',
        'Same delivery behavior after trimming', delivery_mode=delivery_mode, applies_when=f'  {applies_when}  ')
    unchanged = updated['rule']
    assert unchanged['version'] == active['version'] + 1 and unchanged['status'] == 'active'
    assert (unchanged['delivery_mode'], unchanged['applies_when']) == (delivery_mode, applies_when)
    assert updated['governance']['evidence_version'] == draft['version']
    assert updated['governance']['support_count'] == 2
    with uow.read() as tx:
        assert tx.governance.state(active['id']) == original_state
    promoted = p.knowledge.promote_rule(agent, task.id, unchanged['id'], unchanged['version'], 'Reusable')
    assert (promoted.delivery_mode, promoted.applies_when) == (delivery_mode, applies_when)


def test_migration_adds_columns_once(tmp_path):
    database = tmp_path / 'legacy.db'
    with sqlite3.connect(database) as connection:
        connection.executescript('''
            CREATE TABLE rules (id TEXT PRIMARY KEY);
            CREATE TABLE contract_proposals (id TEXT PRIMARY KEY);
            CREATE TABLE deliveries (id TEXT PRIMARY KEY);
            CREATE TABLE rule_versions (rule_id TEXT, version INTEGER, PRIMARY KEY (rule_id, version));
        ''')
    script = str(ROOT / 'scripts' / 'add_rule_applicability.py')
    for _ in range(2):
        subprocess.run([sys.executable, script, '--db', str(database)], check=True, capture_output=True)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(rules)')}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'delivery_mode', 'applies_when'} <= columns and 'delivery_selections' in tables
