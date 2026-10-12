"""Context application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

from ..modules.context import ContextQuery, Delivery, assemble
from ..modules.findings import Finding
from ..modules.knowledge import Priority, relative_path
from ..modules.tasks import Conflict, ProductError, TaskStatus
from ..modules.workspaces import Actor
from .common import _id, _fingerprint
from .workspaces import Workspaces


class Context(Workspaces):
    def get_context(self, actor: Actor, session_id: str, query: ContextQuery,
                    request_id: str | None = None) -> Delivery:
        fingerprint = _fingerprint(query)
        request_id = request_id or _id('request')
        for _ in range(2):
            with self.uow.read() as tx:
                session = self._session(tx, actor, session_id)
                old = tx.context.find_delivery(session_id, request_id)
                if old:
                    if old[0] != fingerprint:
                        raise Conflict('request_id already used for another query.')
                    return old[1]
                project_revision = tx.workspaces.project_revision(session.project_id)
                task = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
                effective_task = task.id if task and task.status in (TaskStatus.ACTIVE, TaskStatus.TESTING) else None
                task_revision = task.revision if task else None
                knowledge_revision = session.knowledge_revision
                rules = tuple(tx.knowledge.visible_rules(session.project_id, effective_task))
                requirements = tuple(tx.requirements.active_requirements(effective_task)) if effective_task else ()
                known = tx.feedback.known_rules(session_id)
                findings = tuple(tx.context.pending_findings(session.project_id, effective_task)) if effective_task else ()
                conflicts = tuple(tx.feedback.conflict_issues(session.project_id, effective_task))
            result = assemble(_id('delivery'), query, rules, requirements, known, findings, conflicts)
            with self.uow.write() as tx:
                current = self._session(tx, actor, session_id)
                old = tx.context.find_delivery(session_id, request_id)
                if old:
                    if old[0] != fingerprint:
                        raise Conflict('request_id already used for another query.')
                    return old[1]
                task_now = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
                if (tx.workspaces.project_revision(session.project_id), task_now.revision if task_now else None,
                    current.knowledge_revision) != (project_revision, task_revision, knowledge_revision):
                    continue
                tx.context.save_delivery(session_id, request_id, fingerprint, result)
                tx.audit.record(session.project_id, actor.id, 'context.delivered', result.id,
                         {'rules': len(result.rule_refs), 'requirements': len(result.requirement_refs),
                          'findings': len(result.finding_refs)})
                return result
        raise Conflict('Knowledge changed during context assembly; retry the request.')

    def record_finding(self, actor: Actor, session_id: str, target_path: str,
                       text: str, priority: Priority = Priority.P1):
        if not text.strip():
            raise ProductError('Finding text is required.')
        relative_path(target_path, pattern=True)
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Finding requires a Task-bound session.')
            task = tx.workspaces.get_task(session.task_id, session.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('This Task no longer accepts Findings.')
            item = Finding(_id('finding'), session.project_id, task.id,
                           session.id, target_path, text, priority)
            tx.context.record_finding(item)
            tx.audit.record(session.project_id, actor.id, 'finding.recorded', item.id, {'task_id': task.id})
            return item
