"""Explicit new-schema migration; refuse an unversioned or old CodeNeuro database."""
from pathlib import Path
import sqlite3

from alembic import context
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL

from codeneuro.adapters.sqlite.schema import metadata


args = context.get_x_argument(as_dictionary=True)
filename = args.get('db') or context.config.get_main_option('codeneuro_db')
if not filename or filename == ':memory:':
    raise RuntimeError('Pass -x db=/absolute/path/to/a/new/database.db; no implicit migration target.')
path = Path(filename).expanduser().resolve()
if path.exists():
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as existing:
        names = {row[0] for row in existing.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if names and 'alembic_version' not in names:
        raise RuntimeError('Refusing an existing database without the new Alembic revision; use a separate offline import.')

url = URL.create('sqlite', database=str(path))


def migrate():
    engine = create_engine(url, connect_args={'timeout': 15})

    @event.listens_for(engine, 'connect')
    def configure(raw, _):
        raw.execute('PRAGMA foreign_keys=ON')
        raw.execute('PRAGMA busy_timeout=15000')
        raw.execute('PRAGMA journal_mode=WAL')

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata,
                          compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


migrate()
