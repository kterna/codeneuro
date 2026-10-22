"""Direct project/task context with immutable request replay and bounded retries."""
from dataclasses import asdict, replace

from ..modules.context import assemble, restore_delivery
from ..modules.findings import Finding
from ..modules.knowledge import Priority, relative_path
from ..modules.tasks import Conflict, ProductError
from .common import _id, replay
from .workspaces import Workspaces
from .topics import require_topics


class Context(Workspaces):
    def _snapshot(self, tx, project_id, task_id):
        revision = tx.workspaces.project_revision(project_id)
        taxonomy = tx.topics.state(project_id)
        task, parent = self._task(tx, task_id, project_id) if task_id else (None, None)
        signature = (revision, taxonomy, parent.version if parent else None, task.version if task else None,
                     tx.workspaces.task_context_revision(task.id) if task else None)
        return signature, task, parent, taxonomy

    def get_context(self, actor, project_id, query, request_id=None, *, task_id=None, source=None):
        request_id = request_id or _id('request')
        payload = {'task_id': task_id, 'query': asdict(query), 'source': source or {}}
        for _ in range(2):
            with self.uow.read() as tx:
                tx.workspaces.project_revision(project_id)
                fingerprint, old = replay(tx, project_id, 'context.get', request_id, payload)
                if old:
                    return restore_delivery(old)
                signature, task, parent, taxonomy = self._snapshot(tx, project_id, task_id)
                if query.topics and not taxonomy['topic_query_enabled']:
                    raise Conflict('Topic queries are disabled until project classification is reviewed.')
                require_topics(tx, project_id, query.topics, lock=False)
                resolved = tuple(asdict(tx.topics.get(project_id, key)) for key in query.topics)
                eligible = bool(task and not task.archived_at and not parent.archived_at
                                and parent.status in ('active', 'accepting')
                                and task.status in ('active', 'testing', 'completed'))
                effective_task = task.id if eligible else None
                rules = tuple(tx.knowledge.visible_rules(project_id, effective_task))
                findings = tuple(tx.context.pending_findings(project_id, effective_task)) if eligible else ()
                conflicts = tuple(tx.feedback.conflict_issues(project_id, effective_task))
                scope = {'project_id': project_id, 'task_id': task_id,
                         'requirement_id': parent.id if parent else None,
                         'requirement_version': parent.version if parent else None,
                         'task_version': task.version if task else None,
                         'requirement_status': parent.status if parent else None,
                         'task_status': task.status if task else None,
                         'read_only': bool(task and (not eligible or task.status == 'completed'))}
            result = replace(assemble(_id('delivery'), query, rules, (parent,) if parent else (), task,
                                      findings, conflicts), taxonomy_revision=taxonomy['taxonomy_revision'],
                             resolved_topics=resolved, scope=scope)
            with self.uow.write() as tx:
                _, old = replay(tx, project_id, 'context.get', request_id, payload)
                if old:
                    return restore_delivery(old)
                if self._snapshot(tx, project_id, task_id)[0] != signature:
                    continue
                provenance = self._source(tx, actor, project_id, source)
                tx.context.save_delivery(project_id, task_id, result, provenance)
                tx.workspaces.record_request(project_id, 'context.get', request_id, fingerprint, asdict(result))
                tx.audit.record(project_id, actor.id, 'context.delivered', result.id,
                    {'task_id': task_id, 'rules': len(result.rule_refs), 'requirements': len(result.requirement_refs),
                     'findings': len(result.finding_refs), 'source': provenance})
                return result
        raise Conflict('Knowledge changed during context assembly; retry the request.')

    def get_delivery(self, actor, delivery_id, project_id=None):
        with self.uow.read() as tx:
            scope = tx.context.delivery_scope(delivery_id)
            if not scope or (project_id is not None and scope['project_id'] != project_id):
                raise ProductError('Delivery not found in the selected scope.', 'not_found')
            return tx.context.get_delivery(delivery_id)

    def open_rules(self, actor, delivery_id, rule_ids, reason, *, project_id=None):
        """Full text for Rules a Delivery offered as one-line cards; the version stays fixed."""
        if not isinstance(rule_ids, (list, tuple)) or not 1 <= len(rule_ids) <= 20:
            raise ProductError('Supply 1–20 Rule ids.')
        if len(set(rule_ids)) != len(rule_ids) or any(not isinstance(item, str) or not item.strip()
                                                     for item in rule_ids):
            raise ProductError('Supply distinct non-empty Rule ids.')
        if not reason.strip():
            raise ProductError('Say why these Rules are needed now.')
        with self.uow.write() as tx:
            scope = tx.context.delivery_scope(delivery_id)
            if not scope or (project_id is not None and scope['project_id'] != project_id):
                raise ProductError('Delivery not found in the selected scope.', 'not_found')
            refs = {row['rule_id']: row for row in tx.context.delivery_rule_refs(delivery_id)}
            missing = [item for item in rule_ids if item not in refs]
            if missing:
                raise ProductError('Rules not offered by this Delivery: ' + ', '.join(missing), 'not_found')
            opened, already_full = [], []
            for rule_id in rule_ids:
                ref = refs[rule_id]
                if ref['representation'] != 'card':
                    already_full.append(rule_id)
                    continue
                snapshot = tx.knowledge.rule_snapshot(rule_id, ref['version'])
                if not snapshot:
                    raise ProductError('Rule version is no longer readable.', 'not_found')
                points = snapshot.get('points') or ()
                markdown = (f"[{snapshot.get('priority')}] {snapshot.get('title')} "
                            f"({rule_id}@{ref['version']})\n"
                            + '\n'.join(f'- {point}' for point in points) + '\n')
                opened.append({'id': rule_id, 'version': ref['version'],
                               'priority': snapshot.get('priority'), 'title': snapshot.get('title'),
                               'applies_when': snapshot.get('applies_when') or '', 'markdown': markdown})
                if not tx.context.selection(delivery_id, rule_id):
                    tx.context.record_selection(delivery_id, rule_id, ref['version'], reason.strip(), actor.id)
            if opened:
                tx.audit.record(scope['project_id'], actor.id, 'delivery.rules_opened', delivery_id,
                                {'rules': [item['id'] for item in opened], 'reason': reason.strip()})
            return {'delivery_id': delivery_id, 'rules': opened, 'already_full': already_full}

    def record_finding(self, actor, task_id, target_path, text, priority=Priority.P1, *, topics, source=None):
        if not text.strip():
            raise ProductError('Finding text is required.')
        if target_path is not None:
            relative_path(target_path, pattern=True)
        if not topics or not isinstance(priority, Priority):
            raise ProductError('Finding requires registered topics and a valid priority.')
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id, writable=True)
            require_topics(tx, task.project_id, topics)
            item = Finding(_id('finding'), task.project_id, task.id, target_path, text,
                           priority, topics=tuple(sorted(topics)))
            tx.context.record_finding(item)
            tx.audit.record(task.project_id, actor.id, 'finding.recorded', item.id,
                {'task_id': task.id, 'source': self._source(tx, actor, task.project_id, source)})
            return item

    def update_finding(self, actor, finding_id, expected_version, reason, topics=None, resolve=False,
                       *, task_id=None, project_id=None):
        if not reason.strip() or type(resolve) is not bool:
            raise ProductError('A reason and explicit resolution flag are required.')
        with self.uow.write() as tx:
            item = tx.context.get_finding(finding_id)
            if not item or (task_id is not None and item.task_id != task_id):
                raise ProductError('Finding outside the selected Task.', 'not_found')
            if task_id is None and (actor.role != 'human' or item.project_id != project_id):
                raise ProductError('Select the Finding Task or use the human project review entry.', 'forbidden')
            self._task(tx, item.task_id, item.project_id, writable=not resolve)
            if item.version != expected_version or item.status != 'pending_review':
                raise Conflict('Finding version or state changed.')
            keys = item.topics if topics is None else tuple(sorted(topics))
            if not resolve and not keys:
                raise ProductError('Pending Findings require topics.')
            require_topics(tx, item.project_id, keys)
            changed = replace(item, topics=keys, status='resolved' if resolve else item.status, version=item.version + 1)
            tx.context.update_finding(changed)
            tx.audit.record(item.project_id, actor.id, 'finding.updated', item.id,
                {'version': changed.version, 'reason': reason, 'resolved': resolve})
            return changed
