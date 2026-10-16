"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
import sqlalchemy as sa
from ...modules.tasks import Conflict, RequirementStatus, TaskStatus
from . import schema as s
from .common import Repo, _requirement

class RequirementsRepo(Repo):
    def get_requirement(self, requirement_id, task_id):
        return _requirement(self._one(sa.select(s.requirements).where(
            s.requirements.c.id == requirement_id, s.requirements.c.task_id == task_id)))

    def submitted_requirement(self, session_id, request_id):
        return _requirement(self._one(sa.select(s.requirements).where(
            s.requirements.c.session_id == session_id, s.requirements.c.request_id == request_id)))

    def web_requirement(self, project_id, request_id):
        return _requirement(self._one(sa.select(s.requirements).where(
            s.requirements.c.project_id == project_id, s.requirements.c.web_request_id == request_id)))

    def create_requirement(self, item, session_id, request_id):
        self.c.execute(s.requirements.insert().values(id=item.id, project_id=item.project_id,
            task_id=item.task_id, session_id=session_id,
            request_id=request_id if session_id else None,
            web_request_id=request_id if session_id is None else None,
            original_text=item.text, current_text=item.text, status=item.status, version=item.version,
            completion_summary=item.summary))
        self.c.execute(s.requirement_versions.insert().values(requirement_id=item.id,
            version=item.version, original_text=item.text, status=item.status,
            completion_summary=item.summary))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == item.task_id).values(
            revision=s.tasks.c.revision + 1))

    def project_requirements(self, project_id):
        return [_requirement(r) for r in self.c.execute(sa.select(s.requirements).join(
            s.tasks, s.tasks.c.id == s.requirements.c.task_id).where(
            s.requirements.c.project_id == project_id, s.requirements.c.status != RequirementStatus.DELETED,
            s.tasks.c.status != TaskStatus.DELETED).order_by(s.requirements.c.id)).mappings()]

    def task_requirements(self, task_id):
        return [_requirement(r) for r in self.c.execute(sa.select(s.requirements).where(
            s.requirements.c.task_id == task_id, s.requirements.c.status != RequirementStatus.DELETED).order_by(s.requirements.c.id)).mappings()]

    def versions(self, requirement_id):
        return [dict(row) for row in self.c.execute(sa.select(
            s.requirement_versions.c.version, s.requirement_versions.c.original_text.label('text'),
            s.requirement_versions.c.status, s.requirement_versions.c.completion_summary.label('summary')
        ).where(s.requirement_versions.c.requirement_id == requirement_id)
            .order_by(s.requirement_versions.c.version)).mappings()]

    def update_requirement(self, item, expected_version):
        result = self.c.execute(s.requirements.update().where(
            s.requirements.c.id == item.id, s.requirements.c.version == expected_version).values(
            current_text=item.text, status=item.status, version=item.version, completion_summary=item.summary))
        if result.rowcount != 1:
            raise Conflict('Requirement version is stale.')
        self.c.execute(s.requirement_versions.insert().values(requirement_id=item.id,
            version=item.version, original_text=item.text, status=item.status, completion_summary=item.summary))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == item.task_id).values(
            revision=s.tasks.c.revision + 1))

    def reopen_requirement(self, item):
        self.c.execute(s.requirements.update().where(s.requirements.c.id == item.id).values(
            status=RequirementStatus.ACTIVE, version=item.version + 1,
            completion_summary=None))
        self.c.execute(s.requirement_versions.insert().values(requirement_id=item.id,
            version=item.version + 1, original_text=item.text,
            status=RequirementStatus.ACTIVE, completion_summary=None))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == item.task_id).values(
            revision=s.tasks.c.revision + 1))

    def archive_requirement(self, item, summary):
        self.c.execute(s.requirements.update().where(s.requirements.c.id == item.id).values(
            status=RequirementStatus.ARCHIVED, version=item.version + 1,
            completion_summary=summary))
        self.c.execute(s.requirement_versions.insert().values(requirement_id=item.id,
            version=item.version + 1, original_text=item.text,
            status=RequirementStatus.ARCHIVED, completion_summary=summary))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == item.task_id).values(
            revision=s.tasks.c.revision + 1))

    def link_rule(self, requirement_id, rule_id):
        self.c.execute(s.requirement_rule_links.insert().values(
            requirement_id=requirement_id, rule_id=rule_id))

    def linked_live_rule_ids(self, requirement_id):
        statement = sa.select(s.rules.c.id).join(s.requirement_rule_links,
            s.requirement_rule_links.c.rule_id == s.rules.c.id).where(
            s.requirement_rule_links.c.requirement_id == requirement_id,
            s.rules.c.status.in_(('active', 'draft')))
        return [row.id for row in self.c.execute(statement)]

    def linked_requirement(self, rule_id):
        return _requirement(self._one(sa.select(s.requirements).join(
            s.requirement_rule_links,
            s.requirement_rule_links.c.requirement_id == s.requirements.c.id).where(
            s.requirement_rule_links.c.rule_id == rule_id)))

    def active_requirements(self, task_id):
        statement = sa.select(s.requirements).where(s.requirements.c.task_id == task_id,
                     s.requirements.c.status == RequirementStatus.ACTIVE).order_by(s.requirements.c.id)
        return [_requirement(r) for r in self.c.execute(statement).mappings()]
