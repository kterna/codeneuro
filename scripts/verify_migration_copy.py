"""Validate an explicitly supplied standalone SQLite backup on a disposable copy.

The backup is opened immutable/read-only. No server is started and no business data
is printed. This does not classify legacy rules or authorize a production cutover.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from repair_legacy_baseline import inspect as inspect_baseline, repair


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def tables(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def columns(connection, table):
    return [row[1] for row in connection.execute('PRAGMA table_info(' + quoted(table) + ')')]


def rows(connection, table, names):
    return Counter(connection.execute('SELECT ' + ','.join(map(quoted, names)) + ' FROM ' + quoted(table)))


def explicit_indexes(connection):
    return {name: (table, tuple(row[2] for row in connection.execute('PRAGMA index_info(' + quoted(name) + ')')))
            for name, table in connection.execute(
                "SELECT name,tbl_name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--repair-baseline', action='store_true')
    parser.add_argument('--expected-worktrees', type=int)
    parser.add_argument('--expected-rules', type=int)
    args = parser.parse_args(argv)
    if args.repair_baseline and (args.expected_worktrees is None or args.expected_rules is None):
        parser.error('Explicit baseline repair requires both approved candidate counts.')
    source = args.backup.resolve(strict=True)
    if Path(str(source) + '-wal').exists():
        raise ValueError('Use a standalone backup, not a live SQLite file with a WAL sidecar.')
    original_hash = hashlib.sha256(source.read_bytes()).digest()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    from codeneuro.adapters.sqlite.schema import CURRENT_SCHEMA
    from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
    from codeneuro.modules.workspaces import Actor
    from codeneuro.workflows.product import Product

    with tempfile.TemporaryDirectory(prefix='codeneuro-migration-copy-') as directory:
        target = Path(directory) / 'verification.db'
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro&immutable=1', uri=True)) as original:
            assert original.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            source_revision = original.execute('SELECT version_num FROM alembic_version').fetchone()[0]
            assert source_revision == '1f7a79740655', 'This verifier expects the v1 modular schema.'
            missing_worktrees, missing_rules = inspect_baseline(original)
            if not args.repair_baseline:
                assert not missing_worktrees and not missing_rules, 'Source requires an explicit baseline-repair decision.'
            elif (len(missing_worktrees), len(missing_rules)) != (args.expected_worktrees, args.expected_rules):
                raise ValueError('Source repair candidates differ from the approved counts.')
            before = {}
            row_counts = {}
            for table in tables(original):
                row_counts[table] = original.execute('SELECT COUNT(*) FROM ' + quoted(table)).fetchone()[0]
                if table == 'alembic_version':
                    continue
                names = columns(original, table)
                if table == 'rules':
                    names.remove('category')  # Only the current classifier is intentionally removed.
                before[table] = (names, rows(original, table, names))
            indexes = explicit_indexes(original)
            with closing(sqlite3.connect(target)) as copy:
                original.backup(copy)
                repair_result = repair(copy, args.expected_worktrees, args.expected_rules) if args.repair_baseline else None

        env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        migration = subprocess.run([sys.executable, '-B', '-m', 'codeneuro', 'migrate', '--db', str(target)],
            cwd=root, env=env, capture_output=True, text=True)
        if migration.returncode:
            raise RuntimeError('Copy migration failed:\n' + migration.stderr[-4000:])

        with closing(sqlite3.connect(target)) as migrated:
            migrated.execute('PRAGMA foreign_keys=ON')
            assert migrated.execute('SELECT version_num FROM alembic_version').fetchone()[0] == CURRENT_SCHEMA
            assert migrated.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            assert migrated.execute('PRAGMA foreign_key_check').fetchall() == []
            additions = ({'worktrees': args.expected_worktrees, 'rule_versions': args.expected_rules,
                          'audit': args.expected_worktrees + args.expected_rules} if args.repair_baseline else {})
            for table, (names, expected) in before.items():
                actual = rows(migrated, table, names)
                assert not expected - actual, f'Existing historical data changed: {table}'
                assert sum(actual.values()) - sum(expected.values()) == additions.get(table, 0), f'Unexpected rows: {table}'
            actual_indexes = explicit_indexes(migrated)
            for name, definition in indexes.items():
                assert actual_indexes.get(name) == definition, f'Existing index changed: {name}'
            assert {'ix_rule_topics_lookup', 'ix_finding_topics_lookup'} <= actual_indexes.keys()
            assert 'category' not in columns(migrated, 'rules')
            for table in ('rule_versions', 'contract_proposals'):
                assert migrated.execute(f'SELECT COUNT(*) FROM {table} WHERE schema_version != 1').fetchone()[0] == 0
                default = next(row[4] for row in migrated.execute(f'PRAGMA table_info({table})') if row[1] == 'schema_version')
                assert str(default).strip("'\"") == '2'
            for table in ('project_topics', 'rule_topics', 'finding_topics', 'rule_reviews'):
                assert migrated.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
            assert migrated.execute('SELECT COUNT(*) FROM projects WHERE topic_query_enabled != 0 OR taxonomy_revision != 0').fetchone()[0] == 0
            for table, parent in (('rule_topics', 'rules'), ('finding_topics', 'findings')):
                links = {(row[2], row[3], row[4]) for row in migrated.execute(f'PRAGMA foreign_key_list({table})')}
                assert (parent, 'project_id', 'project_id') in links
                assert ('project_topics', 'project_id', 'project_id') in links
                assert ('project_topics', 'topic_key', 'key') in links
            project = migrated.execute('SELECT id FROM projects LIMIT 1').fetchone()
            if project:
                migrated.execute('SAVEPOINT priority_probe')
                statement = ('INSERT INTO rules(id,project_id,title,points_json,patterns_json,priority,status,version) '
                             "VALUES (?,?,'Migration probe','[\"Probe\"]','[]',?,'draft',1)")
                migrated.execute(statement, ('migration-copy-p3-probe', project[0], 'P3'))
                try:
                    migrated.execute(statement, ('migration-copy-p4-probe', project[0], 'P4'))
                except sqlite3.IntegrityError:
                    pass
                else:
                    raise AssertionError('Invalid priority P4 was accepted.')
                migrated.execute('ROLLBACK TO priority_probe')
                migrated.execute('RELEASE priority_probe')

        uow = SqliteUnitOfWork(str(target))
        try:
            product = Product(uow)
            actor = Actor('migration-verifier', 'human')
            for project in product.workspaces.list_projects(actor):
                product.ledger.project(actor, project['id'])
            with uow.read() as tx:
                assert tx.c.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        finally:
            uow.dispose()
    assert hashlib.sha256(source.read_bytes()).digest() == original_hash, 'Original backup changed.'
    print(json.dumps({'result': 'passed', 'source_revision': source_revision, 'target_revision': CURRENT_SCHEMA,
        'original_unchanged': True, 'temporary_copy_removed': True, 'preserved_tables': len(before),
        'row_counts': row_counts, 'baseline_repair': repair_result, 'topic_query_enabled_projects': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
