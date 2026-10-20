"""Atomic imports with explicit project Requirements and child Tasks."""
from copy import deepcopy
import json

import pytest

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from scripts.load_batches_into_codeneuro import load_and_validate, ingest_batches
from helpers import initialize_database, file_query, REVIEW, PLAN


@pytest.fixture
def temp_db(tmp_path):
    path = tmp_path / 'import.db'
    initialize_database(path)
    return str(path)


def batch():
    return {
        'projects': [{'id': 'p', 'name': 'Project'}],
        'topics': [{'project_id': 'p', 'key': 'contracts', 'name': 'Contracts', 'description': 'Imported normative contracts'}],
        'requirements': [{'id': 'r', 'project_id': 'p', 'title': 'Overall goal', 'text': 'Original requirement'}],
        'tasks': [{'id': 't', 'project_id': 'p', 'requirement_id': 'r', 'title': 'Independent work'}],
        'rules': [{'id': 'rule', 'project_id': 'p', 'task_id': 't', 'title': 'Rule', 'points': ['Must hold'],
                   'patterns': ['src/**'], 'priority': 'P1', 'topics': ['contracts'], 'status': 'active', 'validation_spec': REVIEW}],
        'findings': [{'id': 'f', 'project_id': 'p', 'task_id': 't', 'text': 'Unreviewed observation',
                      'target_path': 'src/**', 'topics': ['contracts']}]}


def write_batch(tmp_path, data, name='batch.json'):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return str(path)


def test_multifile_forward_references_dry_run_atomic_import_and_jit(tmp_path, temp_db):
    data = batch()
    first = {'rules': data.pop('rules'), 'findings': data.pop('findings')}
    parsed = load_and_validate([write_batch(tmp_path, first, 'first.json'), write_batch(tmp_path, data, 'second.json')])
    preview = ingest_batches(parsed, temp_db, dry_run=True)
    assert preview['created']['tasks'] == 1
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx: assert not tx.workspaces.list_projects()
    uow.dispose()
    ingest_batches(parsed, temp_db)
    uow = SqliteUnitOfWork(temp_db)
    try:
        product = Product(uow)
        with uow.read() as tx:
            assert tx.workspaces.get_task('t').requirement_id == 'r'
            assert tx.requirements.get_requirement('r').original_text == 'Original requirement'
            assert tx.knowledge.rule_snapshot('rule', 1)['points'] == ['Must hold']
            assert tx.context.get_finding('f').task_id == 't'
            assert len(tx.workspaces.task_versions('t')) == 1
            assert len(tx.requirements.versions('r')) == 2
            assert tx.c.exec_driver_sql('SELECT COUNT(*) FROM rule_reviews').scalar() == 1
            assert tx.c.exec_driver_sql('SELECT COUNT(*) FROM test_reports').scalar() == 0
            assert not tx.workspaces.project_worktrees('p')
            assert not tx.c.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='sessions'").fetchall()
            assert not tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
        delivery = product.context.get_context(Actor('agent'), 'p', file_query(('src/a.py',)), task_id='t')
        assert 'Must hold' in delivery.markdown and ('f', 1) in delivery.finding_refs
    finally: uow.dispose()


@pytest.mark.parametrize('collection,field,value', [
    ('projects', 'name', 'Changed'), ('requirements', 'text', 'Changed'),
    ('tasks', 'description', 'Changed'), ('rules', 'patterns', ['pkg/**']), ('findings', 'priority', 'P2'),
])
def test_duplicate_identity_with_different_semantics_rejected(tmp_path, collection, field, value):
    one, two = batch(), batch()
    two[collection][0][field] = value
    with pytest.raises(ValueError, match='Conflicting'):
        load_and_validate([write_batch(tmp_path, one, 'one.json'), write_batch(tmp_path, two, 'two.json')])


@pytest.mark.parametrize('collection,field,value', [
    ('tasks', 'project_id', 'other'), ('tasks', 'requirement_id', 'missing'),
    ('rules', 'task_id', 'missing'), ('findings', 'task_id', 'missing'),
])
def test_cross_project_and_missing_parent_references_rejected(tmp_path, collection, field, value):
    data = batch()
    data[collection][0][field] = value
    with pytest.raises(ValueError): load_and_validate([write_batch(tmp_path, data)])


@pytest.mark.parametrize('collection,value', [('tasks', None), ('requirements', {}), ('rules', 1), ('findings', 'text'), ('projects', [None])])
def test_collection_shapes_rejected(tmp_path, collection, value):
    data = batch()
    data[collection] = value
    with pytest.raises(ValueError): load_and_validate([write_batch(tmp_path, data)])


@pytest.mark.parametrize('collection,field,value', [
    ('tasks', 'status', 'released'), ('tasks', 'status', 'completed'), ('tasks', 'status', 'archived'),
    ('tasks', 'title', ''), ('tasks', 'description', None), ('requirements', 'status', 'completed'),
    ('requirements', 'text', '  '), ('rules', 'is_global', 'true'), ('rules', 'priority', 'P5'),
    ('rules', 'patterns', ['../outside.py']), ('findings', 'target_path', '/absolute/file'),
    ('rules', 'requirement_id', 'old-link'), ('tasks', 'requirements', [{'text': 'old child'}]),
])
def test_strict_states_paths_and_removed_legacy_fields(tmp_path, collection, field, value):
    data = batch()
    data[collection][0][field] = value
    with pytest.raises(ValueError): load_and_validate([write_batch(tmp_path, data)])


def test_unknown_collections_rejected(tmp_path):
    data = batch()
    data['sessions'] = []
    with pytest.raises(ValueError, match='Expected an object'): load_and_validate([write_batch(tmp_path, data)])


def test_inactive_task_cannot_receive_live_knowledge(tmp_path):
    data = batch()
    data['tasks'][0]['status'] = 'draft'
    with pytest.raises(ValueError, match='active Task'): load_and_validate([write_batch(tmp_path, data)])


def test_unknown_topic_is_rejected_before_any_insert(tmp_path, temp_db):
    data = batch()
    data['rules'][0]['topics'] = ['unknown']
    parsed = load_and_validate([write_batch(tmp_path, data)])
    with pytest.raises(ValueError, match='Unregistered topic'): ingest_batches(parsed, temp_db)
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx: assert not tx.workspaces.list_projects()
    uow.dispose()


def test_identical_snapshot_reimport_does_not_mutate_history(tmp_path, temp_db):
    parsed = load_and_validate([write_batch(tmp_path, batch())])
    ingest_batches(parsed, temp_db)
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx:
        before = {name: tx.c.exec_driver_sql(f'SELECT * FROM {name}').fetchall() for name in
                  ('audit', 'requirements', 'requirement_versions', 'tasks', 'task_versions', 'rules', 'rule_versions', 'project_topics')}
    uow.dispose()
    result = ingest_batches(parsed, temp_db)
    assert not any(result['created'].values())
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx:
        assert all(tx.c.exec_driver_sql(f'SELECT * FROM {name}').fetchall() == rows for name, rows in before.items())
    uow.dispose()


@pytest.mark.parametrize('dry_run', [True, False])
def test_target_collision_rejected_without_partial_writes(tmp_path, temp_db, dry_run):
    ingest_batches(load_and_validate([write_batch(tmp_path, batch())]), temp_db)
    changed = batch()
    changed['projects'].append({'id': 'new', 'name': 'Must not be inserted'})
    changed['tasks'][0]['title'] = 'Different claim'
    parsed = load_and_validate([write_batch(tmp_path, changed, 'changed.json')])
    with pytest.raises(ValueError, match='differs'): ingest_batches(parsed, temp_db, dry_run)
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx:
        assert {row['id'] for row in tx.workspaces.list_projects()} == {'p'}
        assert tx.workspaces.get_task('t').title == 'Independent work'
    uow.dispose()


@pytest.mark.parametrize('table', ['rule_versions', 'task_versions', 'requirement_versions'])
def test_missing_current_snapshot_requires_explicit_repair(tmp_path, temp_db, table):
    parsed = load_and_validate([write_batch(tmp_path, batch())])
    ingest_batches(parsed, temp_db)
    uow = SqliteUnitOfWork(temp_db)
    with uow.write() as tx:
        if table == 'rule_versions': tx.c.exec_driver_sql('DELETE FROM rule_reviews')
        tx.c.exec_driver_sql(f'DELETE FROM {table}')
    uow.dispose()
    with pytest.raises(ValueError, match='snapshot'): ingest_batches(parsed, temp_db)


def test_failed_audit_rolls_back_whole_batch(tmp_path, temp_db):
    uow = SqliteUnitOfWork(temp_db)
    with uow.write() as tx:
        tx.c.exec_driver_sql("CREATE TRIGGER refuse_import BEFORE INSERT ON audit WHEN NEW.action='rule.imported' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    uow.dispose()
    with pytest.raises(Exception, match='injected failure'):
        ingest_batches(load_and_validate([write_batch(tmp_path, batch())]), temp_db)
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx:
        assert not tx.workspaces.list_projects()
        assert tx.c.exec_driver_sql('SELECT COUNT(*) FROM rule_versions').scalar() == 0
    uow.dispose()


def test_import_test_rule_only_creates_draft_without_evidence(tmp_path, temp_db):
    data = batch()
    data['rules'][0].update(validation_spec=PLAN, status='active')
    with pytest.raises(ValueError, match='do not invent'): load_and_validate([write_batch(tmp_path, data)])
    data['rules'][0]['status'] = 'draft'
    ingest_batches(load_and_validate([write_batch(tmp_path, data)]), temp_db)
    uow = SqliteUnitOfWork(temp_db)
    with uow.read() as tx:
        assert tx.knowledge.get_rule('rule').status == 'draft'
        assert tx.governance.state('rule')
        assert tx.c.exec_driver_sql('SELECT COUNT(*) FROM test_reports').scalar() == 0
        assert tx.c.exec_driver_sql('SELECT COUNT(*) FROM rule_reviews').scalar() == 0
    uow.dispose()
