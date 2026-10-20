"""Project requirements and immutable version snapshots."""
from dataclasses import asdict
import json
import sqlalchemy as sa
from ...modules.tasks import Conflict
from . import schema as s
from .common import Repo, _requirement, _json


class RequirementsRepo(Repo):
    def get_requirement(self, requirement_id, project_id=None):
        query = sa.select(s.requirements).where(s.requirements.c.id == requirement_id)
        if project_id is not None:
            query = query.where(s.requirements.c.project_id == project_id)
        return _requirement(self._one(query))

    def project_requirements(self, project_id, *, statuses=None, cursor=None, limit=None):
        query = sa.select(s.requirements).where(s.requirements.c.project_id == project_id,
                                               s.requirements.c.deleted_at.is_(None))
        if statuses is not None:
            query = query.where(s.requirements.c.status.in_(statuses))
        if cursor is not None:
            query = query.where(s.requirements.c.id > cursor)
        query = query.order_by(s.requirements.c.id)
        if limit is not None:
            query = query.limit(limit)
        return [_requirement(row) for row in self.c.execute(query).mappings()]

    def _snapshot(self, item):
        self.c.execute(s.requirement_versions.insert().values(requirement_id=item.id,
            version=item.version, snapshot_json=_json(asdict(item))))

    def create_requirement(self, item):
        self.c.execute(s.requirements.insert().values(**asdict(item)))
        self._snapshot(item)

    def update_requirement(self, item, expected_version):
        result = self.c.execute(s.requirements.update().where(s.requirements.c.id == item.id,
            s.requirements.c.version == expected_version).values(**asdict(item)))
        if result.rowcount != 1:
            raise Conflict('Requirement version is stale.')
        self._snapshot(item)

    def versions(self, requirement_id, cursor=None, limit=20):
        query = sa.select(s.requirement_versions).where(s.requirement_versions.c.requirement_id == requirement_id)
        if cursor is not None:
            query = query.where(s.requirement_versions.c.version > cursor)
        return [json.loads(row.snapshot_json) for row in self.c.execute(
            query.order_by(s.requirement_versions.c.version).limit(limit))]

    def progress(self, requirement_ids):
        query = sa.select(s.tasks.c.requirement_id, sa.func.count().label('total'),
            sa.func.sum(sa.case((s.tasks.c.status == 'completed', 1), else_=0)).label('completed')).where(
                s.tasks.c.requirement_id.in_(requirement_ids), s.tasks.c.deleted_at.is_(None)).group_by(s.tasks.c.requirement_id)
        return {row.requirement_id: {'total': row.total, 'completed': row.completed} for row in self.c.execute(query)}
