"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlalchemy as sa
from ...modules.context import Delivery
from ...modules.findings import Finding
from ...modules.knowledge import Priority
from . import schema as s
from .common import Repo, _json

class ContextRepo(Repo):
    def record_finding(self, finding: Finding):
        self.c.execute(s.findings.insert().values(id=finding.id, project_id=finding.project_id,
            task_id=finding.task_id, session_id=finding.session_id,
            target_path=finding.target_path, text=finding.text, priority=finding.priority,
            version=finding.version, status=finding.status))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == finding.task_id).values(
            revision=s.tasks.c.revision + 1))

    def pending_findings(self, project_id, task_id):
        statement = sa.select(s.findings).where(s.findings.c.project_id == project_id,
            s.findings.c.task_id == task_id, s.findings.c.status == 'pending_review')
        return [self._finding(row) for row in self.c.execute(statement)]

    def project_findings(self, project_id):
        statement = sa.select(s.findings).where(s.findings.c.project_id == project_id)
        return [self._finding(row) for row in self.c.execute(statement)]

    @staticmethod
    def _finding(row):
        return Finding(row.id, row.project_id, row.task_id, row.session_id,
                       row.target_path, row.text, Priority(row.priority), row.version, row.status)

    def find_delivery(self, session_id, request_id):
        row = self._one(sa.select(s.deliveries).where(s.deliveries.c.session_id == session_id,
                                                   s.deliveries.c.request_id == request_id))
        if not row:
            return None
        value = json.loads(row['response_json'])
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
