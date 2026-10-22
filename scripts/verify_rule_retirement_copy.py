"""Verify explicit retirements on a disposable SQLite backup, never on the source.

Usage: python scripts/verify_rule_retirement_copy.py --source /path/to/hub.db \
    --project project-id --rule rule-id --delivery delivery-id
Repeat --rule and --delivery for the reviewed targets and real query samples.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product


def rows(connection, table):
    return connection.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()


def verify(source: Path, project_id: str, rule_ids: list[str], delivery_ids: list[str]):
    source = source.resolve(strict=True)
    if not rule_ids or len(set(rule_ids)) != len(rule_ids) or not delivery_ids or len(set(delivery_ids)) != len(delivery_ids):
        raise ValueError('Select distinct Rule IDs and actual Delivery IDs explicitly.')
    with tempfile.TemporaryDirectory(prefix='codeneuro-retirement-') as directory:
        target = Path(directory) / 'copy.db'
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied)
            assert copied.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        uow = SqliteUnitOfWork(str(target))
        try:
            product = Product(uow)
            reader, reviewer = Actor('copy-reader'), Actor('copy-verification', 'human')
            with closing(sqlite3.connect(target)) as copied:
                immutable_tables = ('feedback', 'issues', 'requirements', 'requirement_versions', 'tasks', 'task_versions')
                original_tables = {table: rows(copied, table) for table in immutable_tables}
                snapshots = {(r[0], r[1]): r[2] for r in copied.execute('SELECT rule_id,version,snapshot_json FROM rule_versions')}
                deliveries = dict(copied.execute('SELECT id,response_json FROM deliveries'))
                saved = [copied.execute('SELECT project_id,task_id,response_json FROM deliveries WHERE id=?', (identity,)).fetchone()
                         for identity in delivery_ids]
            with uow.read() as tx:
                rules = {r['id']: r for r in tx.knowledge.project_rules(project_id)}
            selected = {identity: rules[identity] for identity in rule_ids}
            assert all(r['task_id'] is None and r['status'] == 'active' for r in selected.values())
            scenarios = []
            for identity, record in zip(delivery_ids, saved):
                if not record or record[0] != project_id:
                    raise ValueError(f'Delivery outside the selected project: {identity}')
                query_data = json.loads(record[2])['query']
                query = ContextQuery(**{**query_data, 'priorities': tuple(Priority(p) for p in query_data['priorities']),
                                        'files': tuple(query_data['files']), 'topics': tuple(query_data['topics'])})
                before = product.context.get_context(reader, project_id, query, task_id=record[1])
                scenarios.append((identity, record[1], query, before))
            assert any(set(rule_ids) & {r[0] for r in before.rule_refs} for _, _, _, before in scenarios), 'No selected Rule matched any sample.'
            for identity, rule in selected.items():
                product.knowledge.retire_project_rule(reviewer, project_id, identity, rule['version'],
                    'Isolated copy verification only; no production retirement', confirmed=True, request_id='copy-retire-' + identity)
            outcomes = []
            for identity, task_id, query, before in scenarios:
                after = product.context.get_context(reader, project_id, query, task_id=task_id)
                expected = tuple(r for r in before.rule_refs if r[0] not in selected)
                assert after.rule_refs == expected, identity
                outcomes.append({'delivery_id': identity, 'removed_rule_ids': [r[0] for r in before.rule_refs if r[0] in selected],
                                 'retained_rule_ids': [r[0] for r in after.rule_refs]})
            with uow.read() as tx:
                current = {r['id']: r for r in tx.knowledge.project_rules(project_id)}
            assert current.keys() == rules.keys()
            for identity, original_rule in rules.items():
                expected = {**original_rule, 'status': 'deprecated', 'version': original_rule['version'] + 1} if identity in selected else original_rule
                assert current[identity] == expected, identity
            with closing(sqlite3.connect(target)) as copied:
                assert all(rows(copied, table) == old for table, old in original_tables.items())
                actual_snapshots = {(r[0], r[1]): r[2] for r in copied.execute('SELECT rule_id,version,snapshot_json FROM rule_versions')}
                actual_deliveries = dict(copied.execute('SELECT id,response_json FROM deliveries'))
                assert all(actual_snapshots[key] == body for key, body in snapshots.items())
                assert len(actual_snapshots) == len(snapshots) + len(selected)
                assert all(actual_deliveries[key] == body for key, body in deliveries.items())
                assert copied.execute('PRAGMA foreign_key_check').fetchall() == []
                assert copied.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            result = {'result': 'passed', 'source_read_only': True, 'project_id': project_id,
                      'retired_rule_ids_in_copy': rule_ids, 'scenarios': outcomes,
                      'historical_deliveries_preserved': len(deliveries), 'historical_rule_snapshots_preserved': len(snapshots),
                      'feedback_issues_and_task_history_unchanged': True}
        finally:
            uow.dispose()
    return {**result, 'temporary_environment_removed': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--project', required=True)
    parser.add_argument('--rule', required=True, action='append')
    parser.add_argument('--delivery', required=True, action='append')
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.project, args.rule, args.delivery), ensure_ascii=False))


if __name__ == '__main__':
    main()
