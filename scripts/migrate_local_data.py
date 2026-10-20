"""One-time conversion of the local Task/Session database into the current model.

Usage: python scripts/migrate_local_data.py --source old.db --target new.db --mapping mapping.json
The source is read-only; the target must not exist. There is no upgrade chain.
Mapping contains new `requirements` and a `tasks` object keyed by existing Task ID.
Task entries specify requirement_id/status and may include the current Task fields.
Original task-local entries and revisions are retained in the Task's import audit;
original Delivery JSON is copied verbatim. Keep the source as the complete backup.
"""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from codeneuro.adapters.sqlite import schema
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork, initialize_database
from codeneuro.modules.governance import test_event_fingerprint
from codeneuro.modules.tasks import Requirement, RequirementStatus, Task, TaskStatus


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def map_records(tables, mapping):
    """Use explicit business ownership, without inferring acceptance from old states."""
    if set(mapping) != {'requirements', 'tasks'}:
        raise ValueError('Mapping needs requirements and tasks.')
    old_tasks = {row['id']: row for row in tables['tasks']}
    if set(mapping['tasks']) != set(old_tasks):
        raise ValueError('Map every existing Task to its parent Requirement.')
    now = datetime.now(timezone.utc).isoformat()
    parents, tasks = {}, []
    for values in mapping['requirements']:
        entry = dict(values)
        archived = entry.pop('archived', False)
        entry['status'] = RequirementStatus(entry.get('status', 'active'))
        item = Requirement(**entry, original_text=entry['text'], archived_at=now if archived else None)
        if item.id in parents or not item.title.strip() or not item.text.strip():
            raise ValueError('Requirement IDs must be distinct and business goals must not be blank.')
        parents[item.id] = item
    for identity, values in mapping['tasks'].items():
        entry, old = dict(values), old_tasks[identity]
        archived = entry.pop('archived', old['status'] == 'archived')
        entry['status'] = TaskStatus(entry['status'])
        parent = parents[entry['requirement_id']]
        if parent.project_id != old['project_id']:
            raise ValueError('Task and Requirement must belong to the same project.')
        if parent.status == 'draft' and entry['status'] != 'draft':
            raise ValueError('A draft Requirement only accepts draft Tasks.')
        description = entry.pop('description', old['description'])
        notes = [row['current_text'] for row in tables['requirements']
                 if row['task_id'] == identity and row['status'] == 'active']
        if notes:
            description += '\n\n原任务条目：\n' + '\n'.join(notes)
        item = Task(id=identity, project_id=old['project_id'], title=entry.pop('title', old['title']),
                    description=description, archived_at=now if archived else None,
                    deleted_at=now if old['status'] == 'deleted' else None, **entry)
        if item.status == 'paused' and item.paused_from not in ('active', 'testing'):
            raise ValueError('Paused Tasks need paused_from=active or testing.')
        if item.status != 'paused' and item.paused_from is not None:
            raise ValueError('Only paused Tasks have paused_from.')
        if item.status == 'completed' and not (item.verification_summary or '').strip():
            raise ValueError('Completed Tasks need an explicit verification summary.')
        if item.status != 'completed' and (item.verification_summary or item.verification_report_ids):
            raise ValueError('Only completed Tasks carry verification results.')
        for report_id in item.verification_report_ids:
            report = next(row for row in tables['test_reports'] if row['id'] == report_id)
            if ((report['project_id'], report['task_id']) != (item.project_id, item.id)
                    or report['exit_code'] or any(case['status'] == 'failed' for case in json.loads(report['test_cases_json']))):
                raise ValueError('Verification reports must belong to this Task and have passed.')
        tasks.append(item)
    for parent in parents.values():
        children = [item for item in tasks if item.requirement_id == parent.id and not item.deleted_at]
        if parent.status in ('accepting', 'completed') and (not children or any(item.status != 'completed' for item in children)):
            raise ValueError('Acceptance requires all child Tasks to be verified complete.')
        if parent.status == 'completed' and not (parent.completion_summary or '').strip():
            raise ValueError('Overall completion needs an explicit acceptance summary.')
    return list(parents.values()), tasks


def migrate(source, target, mapping):
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    if target.exists():
        raise ValueError('Target already exists; choose a new database file.')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as raw:
        raw.row_factory = sqlite3.Row
        raw.execute('BEGIN')
        names = {row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needed = set(schema.metadata.tables) | {'sessions', 'agent_rule_state', 'requirement_rule_links'}
        tables = {name: [dict(row) for row in raw.execute(f'SELECT * FROM "{name}"')]
                  for name in sorted(needed & names)}
        if 'sessions' not in tables:
            raise ValueError('This script expects the previous local Task/Session database.')
    requirements, tasks = map_records(tables, mapping)
    uow = None
    created = False
    try:
        with target.open('xb'):
            created = True
        initialize_database(str(target))
        uow = SqliteUnitOfWork(str(target))
        with uow.write() as tx:
            tx.c.exec_driver_sql('PRAGMA defer_foreign_keys=ON')

            def insert(name, rows):
                table = schema.metadata.tables[name]
                for row in rows:
                    tx.c.execute(table.insert().values(**{key: value for key, value in row.items() if key in table.c}))

            for name in ('projects', 'project_topics', 'worktrees', 'audit'):
                insert(name, tables[name])
            for item in requirements:
                tx.requirements.create_requirement(item)
            for item in tasks:
                tx.workspaces.create_task(item)
            for name in ('rules', 'rule_topics', 'findings', 'finding_topics', 'contract_proposals', 'rule_reviews'):
                insert(name, tables[name])
            for row in tables['rule_versions']:
                snapshot = {key.removesuffix('_json'): json.loads(value) if key.endswith('_json') and value is not None else value
                            for key, value in row.items() if key != 'schema_version'}
                insert('rule_versions', [{'rule_id': row['rule_id'], 'version': row['version'], 'snapshot_json': encode(snapshot)}])
            for row in tables['test_reports']:
                fingerprint = test_event_fingerprint(json.loads(row['command_json']), json.loads(row['paths_json']),
                    row['exit_code'], row['started_at'], row['finished_at'], json.loads(row['test_cases_json']))
                insert('test_reports', [{**row, 'fingerprint': fingerprint}])
            insert('rule_observations', tables['rule_observations'])
            insert('rule_validation_state', tables['agent_rule_state'])
            sessions = {row['id']: row for row in tables['sessions']}
            for row in tables['issues']:
                insert('issues', [{**row, 'task_id': sessions[row['session_id']]['task_id']}])
            for row in tables['deliveries']:
                session = sessions[row['session_id']]
                insert('deliveries', [{**row, 'project_id': session['project_id'], 'task_id': session['task_id'],
                    'source_json': encode({'workspace': session['workspace'], 'actor_id': session['actor_id']})}])
            for name in ('delivery_rules', 'delivery_findings', 'feedback'):
                insert(name, tables[name])
            parents = {item.id: item for item in requirements}
            for item in tasks:
                old = next(row for row in tables['tasks'] if row['id'] == item.id)
                notes = [row for row in tables['requirements'] if row['task_id'] == item.id]
                identities = {row['id'] for row in notes}
                tx.audit.record(item.project_id, 'local-import', 'task.history_imported', item.id, {
                    'original_task': old, 'task_entries': notes,
                    'entry_revisions': [row for row in tables['requirement_versions'] if row['requirement_id'] in identities],
                    'entry_rules': [row for row in tables['requirement_rule_links'] if row['requirement_id'] in identities],
                    'entry_deliveries': [row for row in tables['delivery_requirements'] if row['requirement_id'] in identities],
                })
                parent = parents[item.requirement_id]
                if item.archived_at or item.deleted_at or parent.archived_at or parent.status == 'completed':
                    tx.knowledge.deprecate_task_rules(item.id)
            if tx.c.exec_driver_sql('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Converted data contains broken references.')
            if tx.c.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
                raise ValueError('Converted database failed its integrity check.')
        return {'result': 'passed', 'requirements': len(requirements), 'tasks': len(tasks),
                'rules': len(tables['rules']), 'deliveries': len(tables['deliveries']), 'source_read_only': True}
    except BaseException:
        if uow:
            uow.dispose()
        if created:
            for filename in (target, Path(str(target) + '-wal'), Path(str(target) + '-shm')):
                filename.unlink(missing_ok=True)
        raise
    finally:
        if uow:
            uow.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--mapping', required=True, help='Business ownership and status mapping JSON')
    args = parser.parse_args()
    mapping = json.loads(Path(args.mapping).read_text(encoding='utf-8'))
    print(encode(migrate(args.source, args.target, mapping)))


if __name__ == '__main__':
    main()
