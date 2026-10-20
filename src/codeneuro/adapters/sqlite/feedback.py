"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
import json
import sqlalchemy as sa
from ...modules.findings import Issue
from . import schema as s
from .common import Repo, _json

class FeedbackRepo(Repo):
    def current_rule_scores(self, project_id):
        joined = s.rules.outerjoin(s.feedback, sa.and_(
            s.feedback.c.rule_id == s.rules.c.id,
            s.feedback.c.rule_version == s.rules.c.version))
        statement = sa.select(s.rules.c.id,
            sa.select(sa.func.count()).select_from(s.delivery_rules).where(
                s.delivery_rules.c.rule_id == s.rules.c.id,
                s.delivery_rules.c.version == s.rules.c.version).correlate(s.rules).scalar_subquery().label('delivery_count'),
            sa.func.count(s.feedback.c.rule_id).label('eval_count'),
            sa.func.coalesce(sa.func.sum(sa.case((s.feedback.c.score == 0, 1), else_=0)), 0).label('known_count'),
            sa.func.round(sa.func.avg(sa.case((s.feedback.c.score > 0, s.feedback.c.score))), 2).label('avg_score')
        ).select_from(joined).where(s.rules.c.project_id == project_id).group_by(s.rules.c.id)
        return {row.id: {'eval_count': row.eval_count, 'known_count': row.known_count,
                         'delivery_count': row.delivery_count,
                         'avg_score': float(row.avg_score) if row.avg_score is not None else None}
                for row in self.c.execute(statement)}

    def record_issue(self, issue: Issue):
        self.c.execute(s.issues.insert().values(id=issue.id, project_id=issue.project_id,
            task_id=issue.task_id, issue_type=issue.issue_type, title=issue.title,
            description=issue.description, file_path=issue.file_path,
            related_rules_json=_json(issue.related_rule_versions),
            suggested_action=issue.suggested_action, status='open'))
        if issue.task_id:
            self.c.execute(s.tasks.update().where(s.tasks.c.id == issue.task_id).values(
                context_revision=s.tasks.c.context_revision + 1))

    def conflict_issues(self, project_id, task_id):
        if not task_id:
            return []
        statement = sa.select(s.issues.c.id, s.issues.c.title,
            s.issues.c.related_rules_json).where(
            s.issues.c.project_id == project_id, s.issues.c.task_id == task_id,
            s.issues.c.issue_type == 'conflict', s.issues.c.status == 'open')
        return [{'id': row.id, 'title': row.title,
                 'rule_refs': tuple(tuple(ref) for ref in json.loads(row.related_rules_json))}
                for row in self.c.execute(statement)]

    def delivered_rule(self, delivery_id, rule_id):
        row = self._one(sa.select(s.delivery_rules.c.version).where(
            s.delivery_rules.c.delivery_id == delivery_id,
            s.delivery_rules.c.rule_id == rule_id))
        return row['version'] if row else None

    def prior_feedback(self, delivery_id, rule_id):
        row = self._one(sa.select(s.feedback.c.score, s.feedback.c.reason).where(
            s.feedback.c.delivery_id == delivery_id, s.feedback.c.rule_id == rule_id))
        return (row['score'], row['reason']) if row else None

    def record_feedback(self, delivery_id, rule_id, version, score, reason):
        self.c.execute(s.feedback.insert().values(delivery_id=delivery_id,
            rule_id=rule_id, rule_version=version, score=score, reason=reason))
