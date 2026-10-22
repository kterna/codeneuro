"""Task findings and immutable delivery snapshots; no execution-session joins."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlalchemy as sa
from ...modules.findings import Finding
from ...modules.knowledge import Priority
from ...modules.tasks import Conflict
from . import schema as s
from .common import Repo, _json


class ContextRepo(Repo):
    def _touch(self, task_id):
        self.c.execute(s.tasks.update().where(s.tasks.c.id == task_id).values(
            context_revision=s.tasks.c.context_revision + 1))

    def record_finding(self, finding):
        self.c.execute(s.findings.insert().values(id=finding.id, project_id=finding.project_id,
            task_id=finding.task_id, target_path=finding.target_path, text=finding.text,
            priority=finding.priority, version=finding.version, status=finding.status))
        self._topics(finding)
        self._touch(finding.task_id)

    def _topics(self, finding):
        self.c.execute(s.finding_topics.delete().where(s.finding_topics.c.finding_id == finding.id))
        if finding.topics:
            self.c.execute(s.finding_topics.insert(), [dict(project_id=finding.project_id,
                finding_id=finding.id, topic_key=key) for key in finding.topics])

    def update_finding(self, finding):
        result = self.c.execute(s.findings.update().where(s.findings.c.id == finding.id,
            s.findings.c.version == finding.version - 1).values(target_path=finding.target_path,
                text=finding.text, priority=finding.priority, status=finding.status, version=finding.version))
        if result.rowcount != 1:
            raise Conflict('Finding version changed.')
        self._topics(finding)
        self._touch(finding.task_id)

    def get_finding(self, finding_id):
        found = self._findings(sa.select(s.findings).where(s.findings.c.id == finding_id))
        return found[0] if found else None

    def pending_findings(self, project_id, task_id):
        return self._findings(sa.select(s.findings).where(s.findings.c.project_id == project_id,
            s.findings.c.task_id == task_id, s.findings.c.status == 'pending_review'))

    def project_findings(self, project_id):
        return self._findings(sa.select(s.findings).where(s.findings.c.project_id == project_id))

    def _findings(self, statement):
        rows = list(self.c.execute(statement))
        topics = {row.id: [] for row in rows}
        if topics:
            for row in self.c.execute(sa.select(s.finding_topics).where(
                    s.finding_topics.c.finding_id.in_(topics)).order_by(s.finding_topics.c.topic_key)):
                topics[row.finding_id].append(row.topic_key)
        return [Finding(row.id, row.project_id, row.task_id, row.target_path, row.text,
            Priority(row.priority), row.version, row.status, tuple(topics[row.id])) for row in rows]

    def get_delivery(self, delivery_id):
        row = self._one(sa.select(s.deliveries.c.response_json).where(s.deliveries.c.id == delivery_id))
        return json.loads(row['response_json']) if row else None

    def delivery_scope(self, delivery_id):
        return self._one(sa.select(s.deliveries.c.project_id, s.deliveries.c.task_id,
            s.deliveries.c.source_json).where(s.deliveries.c.id == delivery_id))

    def delivery_rule_refs(self, delivery_id):
        return [dict(row) for row in self.c.execute(sa.select(s.delivery_rules).where(
            s.delivery_rules.c.delivery_id == delivery_id)).mappings()]

    def selection(self, delivery_id, rule_id):
        return self._one(sa.select(s.delivery_selections).where(
            s.delivery_selections.c.delivery_id == delivery_id,
            s.delivery_selections.c.rule_id == rule_id))

    def record_selection(self, delivery_id, rule_id, version, reason, actor):
        self.c.execute(s.delivery_selections.insert().values(delivery_id=delivery_id,
            rule_id=rule_id, version=version, reason=reason, actor=actor,
            created_at=datetime.now(timezone.utc).isoformat()))

    def delivery_selections(self, delivery_id):
        return [dict(row) for row in self.c.execute(sa.select(s.delivery_selections).where(
            s.delivery_selections.c.delivery_id == delivery_id)).mappings()]

    def save_delivery(self, project_id, task_id, result, source):
        self.c.execute(s.deliveries.insert().values(id=result.id, project_id=project_id, task_id=task_id,
            response_json=_json(asdict(result)), source_json=_json(source),
            created_at=datetime.now(timezone.utc).isoformat()))
        for rule_id, version, representation in result.rule_refs:
            self.c.execute(s.delivery_rules.insert().values(delivery_id=result.id,
                rule_id=rule_id, version=version, representation=representation))
        for requirement_id, version in result.requirement_refs:
            self.c.execute(s.delivery_requirements.insert().values(delivery_id=result.id,
                requirement_id=requirement_id, version=version))
        for task_id, version in result.task_refs:
            self.c.execute(s.delivery_tasks.insert().values(delivery_id=result.id, task_id=task_id, version=version))
        for finding_id, version in result.finding_refs:
            self.c.execute(s.delivery_findings.insert().values(delivery_id=result.id,
                finding_id=finding_id, version=version))
