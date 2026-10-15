"""Explicit topic CRUD and project cutover; shares the knowledge write transaction."""
from dataclasses import asdict, replace
import json

from ..modules.tasks import Conflict, ProductError
from ..modules.topics import Topic, validate_definition, validate_keys
from .workspaces import Workspaces


def require_topics(tx, project_id, keys, *, lock=True):
    validate_keys(keys)
    for key in keys:
        topic = tx.topics.get(project_id, key)
        if topic is None or topic.status != 'active':
            raise ProductError(f'Topic {key!r} is not active in this project.', 'unknown_topic')
    if lock:
        tx.topics.lock(project_id, keys)


class Topics(Workspaces):
    def _project(self, tx, actor, project_id, session_id):
        if (project_id is None) == (session_id is None):
            raise ProductError('Supply either a human project target or an active session.')
        if session_id is not None:
            return self._session(tx, actor, session_id).project_id
        if actor.role != 'human':
            raise ProductError('Agent topic writes require an active session.', 'forbidden')
        tx.workspaces.project_revision(project_id)
        return project_id

    def list_topics(self, actor, project_id, query='', include_deleted=False, cursor=None, limit=50):
        if not 1 <= limit <= 100 or len(query) > 200:
            raise ProductError('Use a bounded topic search and a page size of 1–100.')
        with self.uow.read() as tx:
            state = tx.topics.state(project_id)
            items = tx.topics.list(project_id, query, include_deleted, cursor, limit + 1)
            return {**state, 'items': [asdict(item) for item in items[:limit]],
                    'next_cursor': items[limit - 1].key if len(items) > limit else None}

    def get_topic(self, actor, project_id, key, include_usage=False):
        with self.uow.read() as tx:
            tx.topics.state(project_id)
            topic = tx.topics.get(project_id, key)
            if topic is None:
                raise ProductError('Topic not found.', 'not_found')
            result = asdict(topic)
            if include_usage:
                usage = tx.topics.usage(project_id, key)
                result.update(can_delete=topic.status == 'active' and not any(usage.values()),
                              blocking_references={kind: len(items) for kind, items in usage.items()},
                              references={kind: items[:20] for kind, items in usage.items()})
            return result

    def create_topic(self, actor, key, name, description, reason, *, project_id=None, session_id=None):
        validate_definition(key, name, description)
        if not reason.strip():
            raise ProductError('Topic creation reason is required.')
        with self.uow.write() as tx:
            project_id = self._project(tx, actor, project_id, session_id)
            if tx.topics.get(project_id, key):
                raise Conflict('Topic key already exists or is reserved by deleted history; reuse or choose a new key.')
            topic = Topic(project_id, key, name, description)
            tx.topics.create(topic)
            tx.audit.record(project_id, actor.id, 'topic.created', key, {'reason': reason, 'topic': asdict(topic)})
            return topic

    def update_topic(self, actor, key, expected_version, reason, name=None, description=None,
                     *, project_id=None, session_id=None):
        if not reason.strip():
            raise ProductError('Topic update reason is required.')
        with self.uow.write() as tx:
            project_id = self._project(tx, actor, project_id, session_id)
            old = tx.topics.get(project_id, key)
            if not old or old.status != 'active':
                raise ProductError('Active topic not found.', 'not_found')
            if old.version != expected_version:
                raise Conflict('Topic version changed.')
            changed = replace(old, name=old.name if name is None else name,
                              description=old.description if description is None else description)
            validate_definition(key, changed.name, changed.description)
            if old.definition_locked and changed.description != old.description:
                raise Conflict('An already referenced topic boundary is immutable; explicitly reclassify knowledge instead.')
            if changed == old:
                return old
            changed = replace(changed, version=old.version + 1)
            tx.topics.update(changed, expected_version)
            tx.audit.record(project_id, actor.id, 'topic.updated', key,
                            {'reason': reason, 'before': asdict(old), 'after': asdict(changed)})
            return changed

    def delete_topic(self, actor, key, expected_version, reason, *, project_id=None, session_id=None):
        if not reason.strip():
            raise ProductError('Topic deletion reason is required.')
        with self.uow.write() as tx:
            project_id = self._project(tx, actor, project_id, session_id)
            old = tx.topics.get(project_id, key)
            if old is None:
                raise ProductError('Topic not found.', 'not_found')
            if old.status == 'deleted' and old.version == expected_version + 1:
                return old
            if old.version != expected_version or old.status != 'active':
                raise Conflict('Topic version or state changed.')
            usage = tx.topics.usage(project_id, key)
            if any(usage.values()):
                summary = {kind: {'count': len(items), 'references': items[:20]} for kind, items in usage.items()}
                raise ProductError('Reclassify or resolve references first: ' + json.dumps(summary), 'topic_in_use')
            deleted = replace(old, status='deleted', version=old.version + 1)
            tx.topics.update(deleted, expected_version)
            tx.audit.record(project_id, actor.id, 'topic.deleted', key,
                            {'reason': reason, 'version': deleted.version})
            return deleted

    def enable_query(self, actor, project_id, expected_revision, reason):
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Human confirmation of classification coverage is required.', 'forbidden')
        with self.uow.write() as tx:
            state = tx.topics.state(project_id)
            if state['taxonomy_revision'] != expected_revision:
                raise Conflict('Topic catalogue changed; review current coverage.')
            missing = tx.topics.coverage(project_id)
            if any(missing.values()):
                raise Conflict('Classification/validation/P0 rationale incomplete: ' + json.dumps(
                    {kind: {'count': len(ids), 'ids': ids[:20]} for kind, ids in missing.items()}))
            if not state['topic_query_enabled']:
                tx.topics.enable(project_id, expected_revision)
                tx.audit.record(project_id, actor.id, 'topics.enabled', project_id, {'reason': reason})
            return tx.topics.state(project_id)
