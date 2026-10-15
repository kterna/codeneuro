"""Explicit short SQLite transactions composed from feature repositories."""
from __future__ import annotations
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import URL
from ...modules.tasks import ProductError
from . import schema as s
from .workspaces import WorkspacesRepo
from .requirements import RequirementsRepo
from .knowledge import KnowledgeRepo
from .context import ContextRepo
from .feedback import FeedbackRepo
from .governance import GovernanceRepo
from .audit import AuditRepo
from .topics import TopicsRepo


class SqliteTransaction:
    def __init__(self, connection):
        self.c = connection
        self.workspaces = WorkspacesRepo(connection)
        self.requirements = RequirementsRepo(connection)
        self.knowledge = KnowledgeRepo(connection)
        self.context = ContextRepo(connection)
        self.feedback = FeedbackRepo(connection)
        self.governance = GovernanceRepo(connection)
        self.audit = AuditRepo(connection)
        self.topics = TopicsRepo(connection)


class SqliteUnitOfWork:
    def __init__(self, filename: str):
        location = Path(filename).resolve()
        if not location.is_file():
            raise ProductError('New schema is not initialized; run the explicit Alembic migration.')
        with closing(sqlite3.connect(location.as_uri() + '?mode=ro', uri=True)) as existing:
            if not existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone():
                raise ProductError('Refusing an unversioned or legacy database.')
            version = existing.execute('SELECT version_num FROM alembic_version').fetchone()
            if not version or version[0] != s.CURRENT_SCHEMA:
                raise ProductError('Database schema version does not match this application.')
        self.engine = sa.create_engine(URL.create('sqlite', database=str(location)),
                                       connect_args={'timeout': 15})

        @event.listens_for(self.engine, 'connect')
        def configure(raw, _):
            raw.execute('PRAGMA foreign_keys=ON')
            raw.execute('PRAGMA busy_timeout=15000')
        # No schema creation, migration or production database writes here.

    @contextmanager
    def read(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql('BEGIN')
            try:
                yield SqliteTransaction(connection)
            finally:
                connection.rollback()

    @contextmanager
    def write(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield SqliteTransaction(connection)
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def dispose(self):
        self.engine.dispose()
