"""Versioned knowledge and immutable proposal snapshots on one SQL connection."""
from dataclasses import asdict, replace
import json

import sqlalchemy as sa

from ...modules.knowledge import ContractProposal, Priority
from ...modules.tasks import Conflict
from . import schema as s
from .common import Repo, _json, _rule


def _proposal(row):
    if not row:
        return None
    return ContractProposal(
        id=row['id'], project_id=row['project_id'], task_id=row['task_id'],
        target_rule_id=row['target_rule_id'], target_version=row['target_version'], title=row['title'],
        points=tuple(json.loads(row['points_json'])), patterns=tuple(json.loads(row['patterns_json'])),
        priority=Priority(row['priority']), topics=tuple(json.loads(row['topics_json'])), reason=row['reason'],
        status=row['status'], decision_reason=row['decision_reason'], reviewer_id=row['reviewer_id'],
        is_global=bool(row['is_global']), priority_reason=row['priority_reason'],
        validation_spec=json.loads(row['validation_spec_json']) if row['validation_spec_json'] else None,
        source_rule_id=row['source_rule_id'], source_version=row['source_version'],
        delivery_mode=row.get('delivery_mode') or 'full', applies_when=row.get('applies_when') or '')


def _content(rule):
    return dict(title=rule.title, points_json=_json(rule.points), patterns_json=_json(rule.patterns),
                priority=rule.priority, status=rule.status, is_global=rule.is_global,
                priority_reason=rule.priority_reason, delivery_mode=rule.delivery_mode,
                applies_when=rule.applies_when,
                validation_spec_json=_json(rule.validation_spec) if rule.validation_spec is not None else None)


class KnowledgeRepo(Repo):
    def _rules(self, statement):
        rows = list(self.c.execute(statement).mappings())
        keys = {row['id']: [] for row in rows}
        if keys:
            for row in self.c.execute(sa.select(s.rule_topics).where(s.rule_topics.c.rule_id.in_(keys))
                                      .order_by(s.rule_topics.c.topic_key)):
                keys[row.rule_id].append(row.topic_key)
        return [_rule(row, keys[row['id']]) for row in rows]

    def project_rules(self, project_id):
        origins = {row.id: {'origin_rule_id': row.origin_rule_id, 'origin_version': row.origin_version}
                   for row in self.c.execute(sa.select(s.rules.c.id, s.rules.c.origin_rule_id,
                       s.rules.c.origin_version).where(s.rules.c.project_id == project_id))}
        return [{**asdict(rule), **origins[rule.id]} for rule in self._rules(sa.select(s.rules).where(
            s.rules.c.project_id == project_id).order_by(s.rules.c.id))]

    def visible_rules(self, project_id, task_id):
        statement = sa.select(s.rules).where(s.rules.c.project_id == project_id,
            s.rules.c.status == 'active',
            sa.or_(s.rules.c.task_id.is_(None), s.rules.c.task_id == task_id))
        return self._rules(statement.order_by(s.rules.c.id))

    def _topics(self, rule):
        self.c.execute(s.rule_topics.delete().where(s.rule_topics.c.rule_id == rule.id))
        if rule.topics:
            self.c.execute(s.rule_topics.insert(), [dict(project_id=rule.project_id,
                rule_id=rule.id, topic_key=key) for key in sorted(rule.topics)])

    def create_rule(self, rule, origin=None):
        self.c.execute(s.rules.insert().values(id=rule.id, project_id=rule.project_id,
            task_id=rule.task_id, version=rule.version, **_content(rule),
            origin_rule_id=origin[0] if origin else None, origin_version=origin[1] if origin else None,
            origin_reason=rule.origin_reason))
        self._topics(rule)
        self._rule_snapshot(rule)
        self._bump_rule_scope(rule)

    def _rule_snapshot(self, rule):
        self.c.execute(s.rule_versions.insert().values(rule_id=rule.id, version=rule.version,
                                                       snapshot_json=_json(asdict(rule))))

    def _bump_rule_scope(self, rule):
        if rule.task_id:
            self.c.execute(s.tasks.update().where(s.tasks.c.id == rule.task_id).values(
                context_revision=s.tasks.c.context_revision + 1))
        else:
            self.c.execute(s.projects.update().where(s.projects.c.id == rule.project_id).values(
                rule_revision=s.projects.c.rule_revision + 1))

    def get_rule(self, rule_id):
        found = self._rules(sa.select(s.rules).where(s.rules.c.id == rule_id))
        return found[0] if found else None

    def rule_snapshot(self, rule_id, version):
        row = self._one(sa.select(s.rule_versions).where(
            s.rule_versions.c.rule_id == rule_id, s.rule_versions.c.version == version))
        return json.loads(row['snapshot_json']) if row else None

    def promoted_rule(self, source_id, source_version):
        found = self._rules(sa.select(s.rules).where(s.rules.c.origin_rule_id == source_id,
                                                   s.rules.c.origin_version == source_version))
        return found[0] if found else None

    def update_rule(self, rule):
        result = self.c.execute(s.rules.update().where(s.rules.c.id == rule.id,
            s.rules.c.version == rule.version - 1).values(version=rule.version, **_content(rule)))
        if result.rowcount != 1:
            raise Conflict('Rule was changed before its versioned mutation.')
        self._topics(rule)
        self._rule_snapshot(rule)
        self._bump_rule_scope(rule)

    def deprecate_rule(self, rule):
        self.update_rule(replace(rule, version=rule.version + 1, status='deprecated'))

    def deprecate_task_rules(self, task_id):
        for rule in self._rules(sa.select(s.rules).where(s.rules.c.task_id == task_id,
                                                       s.rules.c.status.in_(('active', 'draft')))):
            self.deprecate_rule(rule)

    def create_proposal(self, proposal):
        values = asdict(proposal)
        for name in ('points', 'patterns', 'topics', 'validation_spec'):
            value = values.pop(name)
            values[name + '_json'] = _json(value) if value is not None else None
        self.c.execute(s.contract_proposals.insert().values(**values))
        self.c.execute(s.tasks.update().where(s.tasks.c.id == proposal.task_id).values(
            context_revision=s.tasks.c.context_revision + 1))

    def get_proposal(self, proposal_id):
        return _proposal(self._one(sa.select(s.contract_proposals).where(s.contract_proposals.c.id == proposal_id)))

    def list_proposals(self, project_id):
        return [_proposal(row) for row in self.c.execute(sa.select(s.contract_proposals).where(
            s.contract_proposals.c.project_id == project_id).order_by(s.contract_proposals.c.id)).mappings()]

    def decide_proposal(self, proposal, status, reason, reviewer_id):
        result = self.c.execute(s.contract_proposals.update().where(
            s.contract_proposals.c.id == proposal.id, s.contract_proposals.c.status == 'pending').values(
                status=status, decision_reason=reason, reviewer_id=reviewer_id))
        if result.rowcount != 1:
            raise Conflict('Contract proposal already has a decision.')
