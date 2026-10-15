"""Topic catalogue and reference queries on the caller's transaction."""
from dataclasses import asdict
import json

import sqlalchemy as sa

from ...modules.tasks import Conflict, ProductError
from ...modules.topics import Topic
from . import schema as s
from .common import Repo


class TopicsRepo(Repo):
    def state(self, project_id):
        row = self._one(sa.select(s.projects.c.taxonomy_revision, s.projects.c.topic_query_enabled)
                        .where(s.projects.c.id == project_id))
        if row is None:
            raise ProductError('Project not found.', 'not_found')
        return row

    def bump(self, project_id):
        self.c.execute(s.projects.update().where(s.projects.c.id == project_id).values(
            taxonomy_revision=s.projects.c.taxonomy_revision + 1))

    def get(self, project_id, key):
        row = self._one(sa.select(s.project_topics).where(
            s.project_topics.c.project_id == project_id, s.project_topics.c.key == key))
        return Topic(**row) if row else None

    def list(self, project_id, query='', include_deleted=False, cursor=None, limit=50):
        stmt = sa.select(s.project_topics).where(s.project_topics.c.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(s.project_topics.c.status == 'active')
        if query:
            stmt = stmt.where(sa.or_(s.project_topics.c.key.contains(query, autoescape=True),
                                   s.project_topics.c.name.contains(query, autoescape=True)))
        if cursor:
            stmt = stmt.where(s.project_topics.c.key > cursor)
        return [Topic(**dict(row)) for row in self.c.execute(
            stmt.order_by(s.project_topics.c.key).limit(limit)).mappings()]

    def create(self, topic):
        self.c.execute(s.project_topics.insert().values(**asdict(topic)))
        self.bump(topic.project_id)

    def update(self, topic, expected_version):
        values = asdict(topic)
        values.pop('project_id')
        values.pop('key')
        result = self.c.execute(s.project_topics.update().where(
            s.project_topics.c.project_id == topic.project_id, s.project_topics.c.key == topic.key,
            s.project_topics.c.version == expected_version).values(**values))
        if result.rowcount != 1:
            raise Conflict('Topic changed; refresh its version.')
        self.bump(topic.project_id)

    def lock(self, project_id, keys):
        result = self.c.execute(s.project_topics.update().where(
            s.project_topics.c.project_id == project_id, s.project_topics.c.key.in_(keys),
            s.project_topics.c.definition_locked.is_(False)).values(
                definition_locked=True, version=s.project_topics.c.version + 1))
        if result.rowcount:
            self.bump(project_id)

    def usage(self, project_id, key):
        rules = sa.select(s.rules.c.id, s.rules.c.version, s.rules.c.status).join(
            s.rule_topics, s.rule_topics.c.rule_id == s.rules.c.id).where(
                s.rule_topics.c.project_id == project_id, s.rule_topics.c.topic_key == key,
                s.rules.c.status.in_(('active', 'draft')))
        findings = sa.select(s.findings.c.id, s.findings.c.version, s.findings.c.status).join(
            s.finding_topics, s.finding_topics.c.finding_id == s.findings.c.id).where(
                s.finding_topics.c.project_id == project_id, s.finding_topics.c.topic_key == key,
                s.findings.c.status == 'pending_review')
        proposals = sa.select(s.contract_proposals.c.id, s.contract_proposals.c.topics_json,
                              s.contract_proposals.c.status).where(
            s.contract_proposals.c.project_id == project_id, s.contract_proposals.c.status == 'pending')
        return {
            'rules': [dict(row) for row in self.c.execute(rules).mappings()],
            'findings': [dict(row) for row in self.c.execute(findings).mappings()],
            'proposals': [{'id': row.id, 'status': row.status} for row in self.c.execute(proposals)
                          if key in json.loads(row.topics_json)],
        }

    def coverage(self, project_id):
        rule_topic = sa.exists(sa.select(s.rule_topics.c.rule_id).join(s.project_topics, sa.and_(
            s.rule_topics.c.project_id == s.project_topics.c.project_id,
            s.rule_topics.c.topic_key == s.project_topics.c.key)).where(
                s.rule_topics.c.rule_id == s.rules.c.id, s.project_topics.c.status == 'active'))
        finding_topic = sa.exists(sa.select(s.finding_topics.c.finding_id).join(s.project_topics, sa.and_(
            s.finding_topics.c.project_id == s.project_topics.c.project_id,
            s.finding_topics.c.topic_key == s.project_topics.c.key)).where(
                s.finding_topics.c.finding_id == s.findings.c.id, s.project_topics.c.status == 'active'))
        rules = self.c.execute(sa.select(s.rules.c.id).where(s.rules.c.project_id == project_id,
            s.rules.c.status == 'active', sa.or_(
                sa.and_(s.rules.c.is_global.is_(False), ~rule_topic),
                sa.and_(s.rules.c.priority == 'P0', sa.func.trim(s.rules.c.priority_reason) == ''),
                s.rules.c.validation_spec_json.is_(None)))).scalars().all()
        findings = self.c.execute(sa.select(s.findings.c.id).where(
            s.findings.c.project_id == project_id, s.findings.c.status == 'pending_review',
            ~finding_topic)).scalars().all()
        return {'rules': list(rules), 'findings': list(findings)}

    def enable(self, project_id, expected_revision):
        result = self.c.execute(s.projects.update().where(s.projects.c.id == project_id,
            s.projects.c.taxonomy_revision == expected_revision).values(
                topic_query_enabled=True, taxonomy_revision=s.projects.c.taxonomy_revision + 1))
        if result.rowcount != 1:
            raise Conflict('Topic catalogue changed before activation.')
