"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
from datetime import datetime, timezone
import sqlalchemy as sa
from . import schema as s
from .common import Repo, _json

class AuditRepo(Repo):
    def project_audit(self, project_id, limit=100, before=None):
        statement = sa.select(s.audit).where(s.audit.c.project_id == project_id)
        if before is not None:
            statement = statement.where(s.audit.c.sequence < before)
        statement = statement.order_by(
            s.audit.c.sequence.desc()).limit(limit)
        return [dict(r) for r in self.c.execute(statement).mappings()]

    def record(self, project_id, actor_id, action, entity_id, details):
        self.c.execute(s.audit.insert().values(project_id=project_id, actor=actor_id,
            action=action, entity_id=entity_id, details_json=_json(details),
            created_at=datetime.now(timezone.utc).isoformat()))
