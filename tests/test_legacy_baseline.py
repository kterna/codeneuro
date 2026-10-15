"""Offline baseline repair is explicit, bounded and never invented historical evidence."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from alembic import command
import pytest

from test_topics_v2 import config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_legacy_baseline', ROOT / 'scripts' / 'repair_legacy_baseline.py')
repair_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair_module)


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / 'v1.db'
    command.upgrade(config(path), '1f7a79740655')
    with closing(sqlite3.connect(path)) as c:
        c.execute("INSERT INTO projects(id,name) VALUES ('p','Fixture')")
        c.execute("INSERT INTO tasks(id,project_id,title,status) VALUES ('t','p','Fixture task','active')")
        c.execute("INSERT INTO sessions(id,project_id,task_id,worktree_id,workspace,agent_client,actor_id,debug,state) VALUES ('s','p','t','missing','/synthetic','mcp','agent',0,'active')")
        c.execute("INSERT INTO rules(id,project_id,title,points_json,patterns_json,priority,category,status,version) VALUES ('r','p','Fixture rule','[\"Keep it\"]','[\"**\"]','P0','business','active',1)")
        c.commit()
    return path


def test_baseline_requires_exact_approval_and_preserves_current_facts(legacy):
    with closing(sqlite3.connect(legacy)) as c:
        before = c.execute('SELECT * FROM rules').fetchall()
        with pytest.raises(ValueError, match='counts'):
            repair_module.repair(c, 0, 1)
        assert c.execute('SELECT COUNT(*) FROM worktrees').fetchone()[0] == 0
        result = repair_module.repair(c, 1, 1)
        assert result == {'worktrees_added': 1, 'current_rule_baselines_added': 1, 'audit_events_added': 2}
        assert c.execute('SELECT * FROM rules').fetchall() == before
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        assert c.execute('SELECT machine_name,platform,repo_identity FROM worktrees').fetchone() == ('not_attested', 'unknown', None)
        snapshot = c.execute('SELECT rule_id,version,category,title FROM rule_versions').fetchone()
        assert snapshot == ('r', 1, 'business', 'Fixture rule')
        audit = json.loads(c.execute("SELECT details_json FROM audit WHERE action='rule.current_baseline_captured'").fetchone()[0])
        assert audit['historical_reconstruction'] is False and audit['test_validation'] is False


def test_baseline_audit_failure_rolls_back_every_insert(legacy):
    with closing(sqlite3.connect(legacy)) as c:
        c.execute("CREATE TRIGGER refuse_baseline BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'audit failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match='audit failure'):
            repair_module.repair(c, 1, 1)
        assert c.execute('SELECT COUNT(*) FROM worktrees').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM rule_versions').fetchone()[0] == 0


def test_conflicting_session_declarations_are_not_guessed(legacy):
    with closing(sqlite3.connect(legacy)) as c:
        c.execute("INSERT INTO sessions(id,project_id,task_id,worktree_id,workspace,agent_client,actor_id,debug,state) VALUES ('s2','p','t','missing','/different','mcp','agent',0,'active')")
        c.commit()
        with pytest.raises(ValueError, match='Conflicting'):
            repair_module.repair(c, 1, 1)
        assert c.execute('SELECT COUNT(*) FROM worktrees').fetchone()[0] == 0


def test_startup_probe_closes_connection_before_engine_disposal(tmp_path, monkeypatch):
    from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork

    path = tmp_path / 'probe.db'
    command.upgrade(config(path), 'head')
    opened, closed = [], []
    original_connect = sqlite3.connect
    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(self)
            super().close()
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    uow = SqliteUnitOfWork(str(path))
    try:
        assert opened and all(connection in closed for connection in opened)
    finally:
        uow.dispose()


def test_migration_verifier_changes_only_the_disposable_copy(legacy):
    original = hashlib.sha256(legacy.read_bytes()).digest()
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'verify_migration_copy.py'),
        '--backup', str(legacy), '--repair-baseline', '--expected-worktrees', '1', '--expected-rules', '1'],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['result'] == 'passed' and report['original_unchanged'] and report['temporary_copy_removed']
    assert hashlib.sha256(legacy.read_bytes()).digest() == original
    with closing(sqlite3.connect(legacy)) as c:
        assert c.execute('SELECT COUNT(*) FROM rule_versions').fetchone()[0] == 0
        assert c.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '1f7a79740655'
