"""Requirements application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

from dataclasses import replace
from ..modules.tasks import Conflict, ProductError, Requirement, RequirementStatus, Task, TaskStatus, check_archive
from ..modules.workspaces import Actor
from .common import _id
from .workspaces import Workspaces


class Requirements(Workspaces):
    def intake(self, actor: Actor, project_id: str, text: str, request_id: str,
               task_id: str | None = None, title: str | None = None):
        """Web human explicitly selects a Task, or creates it with the original demand."""
        if actor.role != 'human':
            raise ProductError('Web intake requires a human identity.', 'forbidden')
        if not text.strip() or not request_id or len(request_id) > 128:
            raise ProductError('Requirement text and bounded request_id are required.')
        if not task_id and (not title or not title.strip()):
            raise ProductError('A new Task requires a title.')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            existing = tx.requirements.web_requirement(project_id, request_id)
            if existing:
                prior_task = tx.workspaces.get_task(existing.task_id, project_id)
                if (existing.text != text or (task_id and existing.task_id != task_id)
                        or (not task_id and prior_task.title != title.strip())):
                    raise Conflict('Web request_id was already used for another Requirement.')
                return existing
            if task_id:
                task = tx.workspaces.get_task(task_id, project_id)
                if task is None or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                    raise Conflict('Selected Task is not active/testing in this project.')
            else:
                task = Task(_id('task'), project_id, title.strip(), text[:500], TaskStatus.ACTIVE, 0)
                tx.workspaces.create_task(task)
                tx.audit.record(project_id, actor.id, 'task.created', task.id, {})
            item = Requirement(_id('requirement'), project_id, task.id, text,
                               RequirementStatus.ACTIVE, 1, None)
            tx.requirements.create_requirement(item, None, request_id)
            tx.audit.record(project_id, actor.id, 'requirement.submitted', item.id,
                     {'task_id': task.id, 'version': 1, 'source': 'web'})
            return item

    def submit_requirement(self, actor: Actor, session_id: str, text: str,
                           request_id: str | None = None):
        if not text.strip():
            raise ProductError('Original Requirement text is required.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Select a Task before submitting a Requirement.')
            previous = tx.requirements.submitted_requirement(session_id, request_id) if request_id else None
            if previous:
                if previous.text != text:
                    raise Conflict('request_id was reused with different text.')
                return previous
            task = tx.workspaces.get_task(session.task_id, session.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('This Task no longer accepts Requirements.')
            item = Requirement(_id('requirement'), session.project_id, task.id, text,
                               RequirementStatus.ACTIVE, 1, None)
            tx.requirements.create_requirement(item, session_id, request_id)
            tx.audit.record(session.project_id, actor.id, 'requirement.submitted', item.id,
                     {'task_id': task.id, 'version': 1})
            return item

    def archive_requirement(self, actor: Actor, session_id: str, requirement_id: str,
                            expected_version: int, summary: str):
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            task = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
            item = tx.requirements.get_requirement(requirement_id, session.task_id) if task else None
            return self._archive(tx, actor, task, item, expected_version, summary)

    def archive_by_human(self, actor: Actor, project_id: str, task_id: str,
                         requirement_id: str, expected_version: int, summary: str):
        if actor.role != 'human':
            raise ProductError('Human review is required for Web archival.', 'forbidden')
        with self.uow.write() as tx:
            task = tx.workspaces.get_task(task_id, project_id)
            item = tx.requirements.get_requirement(requirement_id, task_id) if task else None
            return self._archive(tx, actor, task, item, expected_version, summary)

    @staticmethod
    def _archive(tx, actor, task, item, expected_version, summary):
        if item is None:
            raise ProductError('Requirement outside this Task.', 'not_found')
        if not check_archive(task, item, expected_version, summary):
            return item
        tx.requirements.archive_requirement(item, summary)
        for rule_id in tx.requirements.linked_active_rule_ids(item.id):
            tx.knowledge.deprecate_rule(tx.knowledge.get_rule(rule_id))
        if not tx.requirements.active_requirements(task.id):
            tx.workspaces.complete_task(task.id)
            tx.knowledge.deprecate_task_rules(task.id)
            tx.audit.record(task.project_id, actor.id, 'task.completed', task.id,
                     {'last_requirement_id': item.id})
        tx.audit.record(task.project_id, actor.id, 'requirement.archived', item.id,
                 {'version': expected_version + 1, 'summary': summary})
        return replace(item, status=RequirementStatus.ARCHIVED,
                       version=item.version + 1, summary=summary)
