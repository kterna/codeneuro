"""One-time addition of Rule delivery fields and delivery selections; safe to re-run.

Usage: python scripts/add_rule_applicability.py --db path/to/hub.db [--dry-run]
Existing Rules keep delivery_mode 'full' with no applicability text, so every
Delivery reads the same as before until a human edits a Rule.
"""
import argparse
import sqlite3
from pathlib import Path

COLUMNS = {
    'rules': (
        ('delivery_mode', "ALTER TABLE rules ADD COLUMN delivery_mode VARCHAR(8) NOT NULL DEFAULT 'full'"),
        ('applies_when', "ALTER TABLE rules ADD COLUMN applies_when VARCHAR(200) NOT NULL DEFAULT ''"),
    ),
    'contract_proposals': (
        ('delivery_mode', "ALTER TABLE contract_proposals ADD COLUMN delivery_mode VARCHAR(8) NOT NULL DEFAULT 'full'"),
        ('applies_when', "ALTER TABLE contract_proposals ADD COLUMN applies_when VARCHAR(200) NOT NULL DEFAULT ''"),
    ),
}

SELECTIONS = """CREATE TABLE IF NOT EXISTS delivery_selections (
    delivery_id VARCHAR(128) NOT NULL REFERENCES deliveries (id),
    rule_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (delivery_id, rule_id),
    FOREIGN KEY (rule_id, version) REFERENCES rule_versions (rule_id, version))"""


def existing(connection, table):
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.db.exists():
        parser.error('Database file does not exist.')

    with sqlite3.connect(args.db) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        applied, skipped = [], []
        for table, columns in COLUMNS.items():
            present = existing(connection, table)
            for name, ddl in columns:
                if name in present:
                    skipped.append(f'{table}.{name}')
                else:
                    applied.append(f'{table}.{name}')
                    if not args.dry_run:
                        connection.execute(ddl)
        has_selections = any(row[0] == 'delivery_selections' for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"))
        if not has_selections:
            applied.append('delivery_selections')
            if not args.dry_run:
                connection.execute(SELECTIONS)
        else:
            skipped.append('delivery_selections')
        if not args.dry_run:
            connection.commit()
            assert connection.execute('PRAGMA foreign_key_check').fetchall() == []

    print('applied: ' + (', '.join(applied) or 'none'))
    print('already present: ' + (', '.join(skipped) or 'none'))
    print('dry run; nothing written' if args.dry_run else 'done')


if __name__ == '__main__':
    main()
