"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
import json
import sqlalchemy as sa
from ...modules.knowledge import ContractProposal, Priority, Rule
from ...modules.tasks import Conflict
from . import schema as s
from .common import Repo, _json, _rule

def _proposal(row):
    return ContractProposal(row['id'], row['project_id'], row['task_id'], row['session_id'],
        row['target_rule_id'], row['target_version'], row['title'],
        tuple(json.loads(row['points_json'])), tuple(json.loads(row['patterns_json'])),
        Priority(row['priority']), row['category'], row['reason'], row['status'],
        row['decision_reason'], row['reviewer_id']) if row else None


class KnowledgeRepo(Repo):
    def project_rules(self, project_id):
        return [{**dict(row), 'points': json.loads(row['points_json']),
                 'patterns': json.loads(row['patterns_json'])}
                for row in self.c.execute(sa.select(s.rules).where(
                    s.rules.c.project_id == project_id).order_by(s.rules.c.id)).mappings()]

    def create_rule(self, rule, origin=None):
        self.c.execute(s.rules.insert().values(id=rule.id, project_id=rule.project_id,
            task_id=rule.task_id, title=rule.title, points_json=_json(rule.points),
            patterns_json=_json(rule.patterns), priority=rule.priority, category=rule.category,
            version=rule.version, status=rule.status, origin_rule_id=origin[0] if origin else None,
            origin_version=origin[1] if origin else None, origin_reason=rule.origin_reason))
        self._rule_snapshot(rule)
        self._bump_rule_scope(rule)

    def _rule_snapshot(self, rule):
        self.c.execute(s.rule_versions.insert().values(rule_id=rule.id, version=rule.version,
            title=rule.title, points_json=_json(rule.points), patterns_json=_json(rule.patterns),
            priority=rule.priority, category=rule.category, status=rule.status))

    def _bump_rule_scope(self, rule):
        if rule.task_id:
            self.c.execute(s.tasks.update().where(s.tasks.c.id == rule.task_id).values(
                revision=s.tasks.c.revision + 1))
        else:
            self.c.execute(s.projects.update().where(s.projects.c.id == rule.project_id).values(
                rule_revision=s.projects.c.rule_revision + 1))

    def get_rule(self, rule_id):
        return _rule(self._one(sa.select(s.rules).where(s.rules.c.id == rule_id)))

    def rule_snapshot(self, rule_id, version):
        row = self._one(sa.select(s.rule_versions).where(
            s.rule_versions.c.rule_id == rule_id, s.rule_versions.c.version == version))
        if row is None:
            return None
        result = dict(row)
        result['points'] = json.loads(result.pop('points_json'))
        result['patterns'] = json.loads(result.pop('patterns_json'))
        return result

    def promoted_rule(self, source_id, source_version):
        return _rule(self._one(sa.select(s.rules).where(s.rules.c.origin_rule_id == source_id,
                     s.rules.c.origin_version == source_version)))

    def update_rule(self, rule):
        result = self.c.execute(s.rules.update().where(
            s.rules.c.id == rule.id, s.rules.c.version == rule.version - 1).values(
            title=rule.title, points_json=_json(rule.points), patterns_json=_json(rule.patterns),
            priority=rule.priority, category=rule.category, status=rule.status,
            version=rule.version))
        if result.rowcount != 1:
            raise Conflict('Rule was changed before its versioned mutation.')
        self._rule_snapshot(rule)
        self._bump_rule_scope(rule)

    def deprecate_rule(self, rule):
        updated = Rule(rule.id, rule.project_id, rule.task_id, rule.title, rule.points,
                       rule.patterns, rule.priority, rule.category, rule.version + 1,
                       'deprecated', rule.origin_reason)
        self.c.execute(s.rules.update().where(s.rules.c.id == rule.id).values(
            status='deprecated', version=updated.version))
        self._rule_snapshot(updated)
        self._bump_rule_scope(updated)

    def deprecate_task_rules(self, task_id):
        found = list(self.c.execute(sa.select(s.rules).where(s.rules.c.task_id == task_id,
            s.rules.c.status.in_(('active', 'draft')))).mappings())
        for row in found:
            self.deprecate_rule(_rule(row))

    def create_proposal(self, proposal):
        self.c.execute(s.contract_proposals.insert().values(id=proposal.id,
            project_id=proposal.project_id, task_id=proposal.task_id,
            session_id=proposal.session_id, target_rule_id=proposal.target_rule_id,
            target_version=proposal.target_version, title=proposal.title,
            points_json=_json(proposal.points), patterns_json=_json(proposal.patterns),
            priority=proposal.priority, category=proposal.category, reason=proposal.reason,
            status=proposal.status))

    def get_proposal(self, proposal_id):
        return _proposal(self._one(sa.select(s.contract_proposals).where(
            s.contract_proposals.c.id == proposal_id)))

    def list_proposals(self, project_id):
        return [_proposal(row) for row in self.c.execute(sa.select(s.contract_proposals).where(
            s.contract_proposals.c.project_id == project_id).order_by(s.contract_proposals.c.id)).mappings()]

    def decide_proposal(self, proposal, status, reason, reviewer_id):
        result = self.c.execute(s.contract_proposals.update().where(
            s.contract_proposals.c.id == proposal.id,
            s.contract_proposals.c.status == 'pending').values(
            status=status, decision_reason=reason, reviewer_id=reviewer_id))
        if result.rowcount != 1:
            raise Conflict('Contract proposal already has a decision.')

    def visible_rules(self, project_id, task_id):
        statement = sa.select(s.rules).where(s.rules.c.project_id == project_id,
            s.rules.c.status == 'active',
            sa.or_(s.rules.c.task_id.is_(None), s.rules.c.task_id == task_id))
        return [_rule(row) for row in self.c.execute(statement).mappings()]
