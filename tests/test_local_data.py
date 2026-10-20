"""Current database initialization and the one-time local data conversion."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from codeneuro.adapters.sqlite import schema
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork, initialize_database
from codeneuro.modules.tasks import ProductError
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from scripts.migrate_local_data import migrate
from helpers import file_query, REVIEW


def test_initialize_empty_database_without_version_catalog(tmp_path):
    path = tmp_path / 'current.db'
    initialize_database(path)
    with closing(sqlite3.connect(path)) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == set(schema.metadata.tables)
    with pytest.raises(ProductError, match='not empty'):
        initialize_database(path)
    uow = SqliteUnitOfWork(str(path))
    uow.dispose()


@pytest.fixture
def previous(tmp_path):
    path = tmp_path / 'previous.db'
    stamp = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path)) as db:
        db.executescript((Path(__file__).parent / 'fixtures/previous_layout.sql').read_text(encoding='utf-8'))
        db.execute('PRAGMA foreign_keys=ON')
        def insert(table, **values):
            db.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
        insert('projects', id='p', name='Synthetic history')
        insert('worktrees', id='w', project_id='p', actor_id='agent', workspace='/fixture', machine_name='fixture', platform='linux')
        insert('tasks', id='t', project_id='p', title='Implementation', description='Old scope', status='active', revision=4)
        insert('tasks', id='archived', project_id='p', title='Stored task', description='Stored scope', status='archived', revision=2)
        insert('sessions', id='s', project_id='p', task_id='t', worktree_id='w', workspace='/fixture', agent_client='mcp', actor_id='agent', debug=0, state='closed')
        insert('requirements', id='entry', project_id='p', task_id='t', original_text='Original clause', current_text='Revised clause', status='active', version=2)
        for revision, text in ((1, 'Original clause'), (2, 'Revised clause')):
            insert('requirement_versions', requirement_id='entry', version=revision, original_text=text, status='active')
        insert('project_topics', project_id='p', key='contracts', name='Contracts', description='Fixture boundary', version=1, status='active', definition_locked=1)
        for identity, task in (('contract', None), ('short-term', 'archived')):
            values = dict(title=identity, points_json='["Keep data"]', patterns_json='["src/**"]', priority='P1', status='active', version=1, validation_spec_json=json.dumps(REVIEW))
            insert('rules', id=identity, project_id='p', task_id=task, **values)
            insert('rule_versions', rule_id=identity, topics_json='["contracts"]', **values)
            insert('rule_topics', project_id='p', rule_id=identity, topic_key='contracts')
        insert('requirement_rule_links', rule_id='contract', requirement_id='entry')
        insert('agent_rule_state', rule_id='short-term', session_id='s', evidence_version=1, half_life_days=30, revision_at=stamp)
        snapshot = {'id': 'delivery', 'markdown': 'Actual original delivery', 'requirement_refs': [['entry', 2]], 'rule_refs': [['contract', 1, 'full']]}
        insert('deliveries', id='delivery', session_id='s', request_id='old-request', fingerprint='old', response_json=json.dumps(snapshot), created_at=stamp)
        insert('delivery_rules', delivery_id='delivery', rule_id='contract', version=1, representation='full')
        insert('delivery_requirements', delivery_id='delivery', requirement_id='entry', version=2)
        insert('feedback', delivery_id='delivery', rule_id='contract', rule_version=1, score=0, reason='Known')
        insert('issues', id='issue', project_id='p', session_id='s', issue_type='coverage', title='Issue', description='Original issue', file_path='src/a.py', related_rules_json='[]', suggested_action='Review')
        now = datetime.now(timezone.utc)
        for identity, zone in (('a', timezone.utc), ('b', timezone(timedelta(hours=8)))):
            insert('test_reports', id=identity, project_id='p', task_id='t', session_id='s', request_id=identity, fingerprint=identity,
                   command_json='["pytest"]', paths_json='["src/a.py"]', exit_code=0,
                   started_at=(now-timedelta(seconds=2)).astimezone(zone).isoformat(),
                   finished_at=(now-timedelta(seconds=1)).astimezone(zone).isoformat(), recorded_at=stamp,
                   source='client_reported', test_cases_json='[{"test_id":"check","status":"passed"}]')
        db.commit()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    mapping = {'requirements': [{'id': 'goal', 'project_id': 'p', 'title': 'Overall goal', 'text': 'Explicit business objective'}],
               'tasks': {'t': {'requirement_id': 'goal', 'status': 'active'}, 'archived': {'requirement_id': 'goal', 'status': 'active'}}}
    return path, tmp_path / 'converted.db', mapping, snapshot


def test_source_layout_is_refused_by_runtime_without_writes(previous):
    source, _, _, _ = previous
    before = source.read_bytes()
    with pytest.raises(ProductError, match='structure differs'):
        SqliteUnitOfWork(str(source))
    assert source.read_bytes() == before


def test_local_copy_retains_history_direct_scope_and_original_delivery(previous):
    source, target, mapping, snapshot = previous
    before = source.read_bytes()
    assert migrate(source, target, mapping)['result'] == 'passed'
    assert source.read_bytes() == before
    uow = SqliteUnitOfWork(str(target))
    try:
        product, actor = Product(uow), Actor('next-agent')
        assert product.context.get_delivery(actor, 'delivery') == snapshot
        fresh = product.context.get_context(actor, 'p', file_query(('src/a.py',)), 'old-request', task_id='t')
        assert fresh.requirement_refs == (('goal', 1),) and fresh.task_refs == (('t', 1),)
        assert 'Revised clause' in fresh.markdown
        with uow.read() as tx:
            names = {row[0] for row in tx.c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
            assert names == set(schema.metadata.tables)
            assert tx.c.exec_driver_sql('SELECT COUNT(DISTINCT fingerprint) FROM test_reports').scalar() == 1
            assert tx.feedback.delivered_rule('delivery', 'contract') == 1
            assert tx.workspaces.get_task('archived').archived_at
            assert tx.workspaces.get_task('archived').status == 'active'
            assert tx.knowledge.get_rule('short-term').status == 'deprecated'
            assert tx.knowledge.rule_snapshot('short-term', 1)['status'] == 'active'
            assert tx.c.exec_driver_sql("SELECT task_id FROM issues WHERE id='issue'").scalar() == 't'
            audit = json.loads(tx.c.exec_driver_sql("SELECT details_json FROM audit WHERE entity_id='t' AND action='task.history_imported'").scalar())
            assert audit['task_entries'][0]['original_text'] == 'Original clause'
            assert len(audit['entry_revisions']) == 2 and audit['entry_deliveries'][0]['requirement_id'] == 'entry'
            assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
    finally:
        uow.dispose()


@pytest.mark.parametrize('bad', ['missing_task', 'cross_project', 'unverified_completion', 'unaccepted_goal'])
def test_invalid_ownership_and_completion_leave_source_unchanged(previous, bad):
    source, target, mapping, _ = previous
    mapping = deepcopy(mapping)
    if bad == 'missing_task': del mapping['tasks']['archived']
    elif bad == 'cross_project': mapping['requirements'][0]['project_id'] = 'other'
    elif bad == 'unverified_completion': mapping['tasks']['t']['status'] = 'completed'
    else: mapping['requirements'][0]['status'] = 'completed'
    before = source.read_bytes()
    with pytest.raises(ValueError): migrate(source, target, mapping)
    assert not target.exists() and source.read_bytes() == before


def test_failed_copy_removes_only_the_new_target(previous, monkeypatch):
    from codeneuro.adapters.sqlite.audit import AuditRepo
    source, target, mapping, _ = previous
    before = source.read_bytes()
    def fail(*args, **kwargs): raise RuntimeError('Injected copy failure')
    monkeypatch.setattr(AuditRepo, 'record', fail)
    with pytest.raises(RuntimeError, match='Injected'): migrate(source, target, mapping)
    assert not target.exists() and source.read_bytes() == before


def test_script_cli_and_existing_target_guard(previous):
    source, target, mapping, _ = previous
    mapping_path = target.parent / 'mapping.json'
    mapping_path.write_text(json.dumps(mapping), encoding='utf-8')
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, '-B', str(root / 'scripts/migrate_local_data.py'), '--source', str(source),
        '--target', str(target), '--mapping', str(mapping_path)], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['source_read_only']
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='already exists'): migrate(source, target, mapping)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
