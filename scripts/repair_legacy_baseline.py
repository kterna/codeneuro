"""Operator-approved v1 baseline repair; not a reconstruction of missing history.

Only unambiguous Worktree declarations and missing current-v1 Rule snapshots are
eligible. Existing content, scope, priority, identity and evidence remain untouched.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


REASON = ('Operator-approved upgrade baseline: preserve current stored facts, '
          'not reconstructed historical versions or verified test evidence.')


def inspect(connection):
    if connection.execute('SELECT version_num FROM alembic_version').fetchall() != [('1f7a79740655',)]:
        raise ValueError('Baseline repair only supports the explicitly reviewed v1 schema.')
    missing = connection.execute('''SELECT DISTINCT s.worktree_id,s.project_id,s.actor_id,s.workspace
        FROM sessions s LEFT JOIN worktrees w ON w.id=s.worktree_id WHERE w.id IS NULL''').fetchall()
    if len({row[0] for row in missing}) != len(missing):
        raise ValueError('Conflicting Session declarations; do not infer a Worktree identity.')
    violations = connection.execute('PRAGMA foreign_key_check').fetchall()
    if any(row[0] != 'sessions' or row[2] != 'worktrees' for row in violations):
        raise ValueError('Foreign key damage exceeds the approved Session/Worktree repair.')
    rules = connection.execute('''SELECT r.id,r.project_id,r.version FROM rules r
        WHERE NOT EXISTS (SELECT 1 FROM rule_versions v WHERE v.rule_id=r.id AND v.version=r.version)''').fetchall()
    if any(version != 1 for _, _, version in rules):
        raise ValueError('Missing later rule versions require a separate history decision.')
    if connection.execute('''SELECT COUNT(*) FROM requirements r WHERE NOT EXISTS
        (SELECT 1 FROM requirement_versions v WHERE v.requirement_id=r.id AND v.version=r.version)''').fetchone()[0]:
        raise ValueError('Missing Requirement history is not part of this repair.')
    if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed.')
    return missing, rules


def repair(connection, expected_worktrees, expected_rules):
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('BEGIN IMMEDIATE')
    try:
        missing, rules = inspect(connection)
        if (len(missing), len(rules)) != (expected_worktrees, expected_rules):
            raise ValueError('Repair candidates changed; obtain approval for the new counts.')
        def audit(project, action, identity, details):
            connection.execute('''INSERT INTO audit(project_id,actor,action,entity_id,details_json,created_at)
                VALUES (?,?,?,?,?,?)''', (project, 'migration-agent', action, identity,
                json.dumps({**details, 'reason': REASON}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        for identity, project, actor, workspace in missing:
            sessions = [row[0] for row in connection.execute('SELECT id FROM sessions WHERE worktree_id=?', (identity,))]
            connection.execute('''INSERT INTO worktrees
                (id,project_id,actor_id,workspace,machine_name,platform,repo_identity,git_branch)
                VALUES (?,?,?,?,'not_attested','unknown',NULL,'')''', (identity, project, actor, workspace))
            audit(project, 'worktree.declaration_baselined', identity,
                  {'source': 'existing_session_declarations', 'session_ids': sessions, 'host_verified': False})
        for identity, project, version in rules:
            connection.execute('''INSERT INTO rule_versions
                (rule_id,version,title,points_json,patterns_json,priority,category,status)
                SELECT id,version,title,points_json,patterns_json,priority,category,status FROM rules WHERE id=?''', (identity,))
            audit(project, 'rule.current_baseline_captured', identity,
                  {'source': 'current_rule_row_at_migration', 'version': version,
                   'historical_reconstruction': False, 'test_validation': False})
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Repair left foreign key violations.')
        if any(inspect(connection)):
            raise ValueError('Repair left missing current records.')
        connection.commit()
        return {'worktrees_added': len(missing), 'current_rule_baselines_added': len(rules),
                'audit_events_added': len(missing) + len(rules)}
    except BaseException:
        connection.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--expected-worktrees', type=int)
    parser.add_argument('--expected-rules', type=int)
    args = parser.parse_args(argv)
    database = args.db.resolve(strict=True)
    if not args.apply:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            worktrees, rules = inspect(connection)
            print(json.dumps({'mode': 'read_only', 'missing_worktrees': len(worktrees), 'missing_current_rules': len(rules)}))
        return
    if not args.backup or args.expected_worktrees is None or args.expected_rules is None:
        parser.error('--apply requires a new backup path and both approved candidate counts')
    backup = args.backup.resolve()
    if backup.exists() or backup == database:
        parser.error('Backup destination must be a new, separate file.')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)  # Includes committed WAL data, unlike a file copy.
        result = repair(connection, args.expected_worktrees, args.expected_rules)
    print(json.dumps({'result': 'applied', 'backup': str(backup), **result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
