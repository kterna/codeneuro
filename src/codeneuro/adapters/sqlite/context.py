"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlalchemy as sa
from ...modules.context import Delivery
from ...modules.findings import Finding
from ...modules.knowledge import Priority
from ...modules.tasks import Conflict
from . import schema as s
from .common import Repo, _json

class ContextRepo(Repo):
    def record_finding(self, finding: Finding):
        self.c.execute(s.findings.insert().values(id=finding.id, project_id=finding.project_id,
            task_id=finding.task_id, session_id=finding.session_id,
            target_path=finding.target_path, text=finding.text, priority=finding.priority,
            version=finding.version, status=finding.status))
        self._topics(finding)
        self.c.execute(s.tasks.update().where(s.tasks.c.id == finding.task_id).values(
            revision=s.tasks.c.revision + 1))

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
        self.c.execute(s.tasks.update().where(s.tasks.c.id == finding.task_id).values(
            revision=s.tasks.c.revision + 1))

    def get_finding(self, finding_id):
        found = self._findings(sa.select(s.findings).where(s.findings.c.id == finding_id))
        return found[0] if found else None

    def pending_findings(self, project_id, task_id):
        statement = sa.select(s.findings).where(s.findings.c.project_id == project_id,
            s.findings.c.task_id == task_id, s.findings.c.status == 'pending_review')
        return self._findings(statement)

    def project_findings(self, project_id):
        return self._findings(sa.select(s.findings).where(s.findings.c.project_id == project_id))

    def _findings(self, statement):
        rows = list(self.c.execute(statement))
        topics = {row.id: [] for row in rows}
        if topics:
            for row in self.c.execute(sa.select(s.finding_topics).where(
                    s.finding_topics.c.finding_id.in_(topics)).order_by(s.finding_topics.c.topic_key)):
                topics[row.finding_id].append(row.topic_key)
        return [Finding(row.id, row.project_id, row.task_id, row.session_id,
            row.target_path, row.text, Priority(row.priority), row.version, row.status,
            tuple(topics[row.id])) for row in rows]

    def find_delivery(self, session_id, request_id):
        row = self._one(sa.select(s.deliveries).where(s.deliveries.c.session_id == session_id,
                                                   s.deliveries.c.request_id == request_id))
        if not row:
            return None
        value = json.loads(row['response_json'])
        value.setdefault('protocol_version', 1)
        if 'query' in value:
            for name in ('priorities', 'topics', 'files'):
                value['query'][name] = tuple(value['query'][name])
        value['resolved_topics'] = tuple(value.get('resolved_topics', ()))
        value['match_reasons'] = {key: tuple(items) for key, items in value.get('match_reasons', {}).items()}
        value['rule_refs'] = tuple(tuple(item) for item in value['rule_refs'])
        value['requirement_refs'] = tuple(tuple(item) for item in value['requirement_refs'])
        value['finding_refs'] = tuple(tuple(item) for item in value.get('finding_refs', ()))
        value['sections'] = {name: tuple(items) for name, items in value.get('sections', {}).items()}
        value['reported_conflicts'] = tuple({**item,
            'rule_refs': tuple(tuple(ref) for ref in item['rule_refs'])}
            for item in value.get('reported_conflicts', ()))
        for name in ('omitted_rule_ids', 'omitted_requirement_ids',
                     'omitted_finding_ids', 'omitted_conflict_ids'):
            value[name] = tuple(value.get(name, ()))
        return row['fingerprint'], Delivery(**value)

    def save_delivery(self, session_id, request_id, fingerprint, result):
        self.c.execute(s.deliveries.insert().values(id=result.id, session_id=session_id,
            request_id=request_id, fingerprint=fingerprint, response_json=_json(asdict(result)),
            created_at=datetime.now(timezone.utc).isoformat()))
        for rule_id, version, representation in result.rule_refs:
            self.c.execute(s.delivery_rules.insert().values(delivery_id=result.id,
                rule_id=rule_id, version=version, representation=representation))
        for requirement_id, version in result.requirement_refs:
            self.c.execute(s.delivery_requirements.insert().values(delivery_id=result.id,
                requirement_id=requirement_id, version=version))
        for finding_id, version in result.finding_refs:
            self.c.execute(s.delivery_findings.insert().values(delivery_id=result.id,
                finding_id=finding_id, version=version))
