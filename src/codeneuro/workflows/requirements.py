"""Requirements application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

from dataclasses import asdict, replace
from ..modules.tasks import Conflict, ProductError, Requirement, RequirementStatus, Task, TaskStatus, check_archive, check_reopen, validate_crud
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

    def list_requirements(self, actor: Actor, session_id: str):
        with self.uow.read() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Select a Task before listing its Requirements.')
            return tx.requirements.task_requirements(session.task_id)

    def reopen_requirement(self, actor: Actor, session_id: str, requirement_id: str,
                           expected_version: int, reason: str):
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            task = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
            item = tx.requirements.get_requirement(requirement_id, session.task_id) if task else None
            return self._reopen(tx, actor, task, item, expected_version, reason)

    def reopen_by_human(self, actor: Actor, project_id: str, task_id: str,
                        requirement_id: str, expected_version: int, reason: str):
        if actor.role != 'human':
            raise ProductError('Human review is required for Web reopening.', 'forbidden')
        with self.uow.write() as tx:
            task = tx.workspaces.get_task(task_id, project_id)
            item = tx.requirements.get_requirement(requirement_id, task_id) if task else None
            return self._reopen(tx, actor, task, item, expected_version, reason)

    @staticmethod
    def _reopen(tx, actor, task, item, expected_version, reason):
        if item is None:
            raise ProductError('Requirement outside this Task.', 'not_found')
        check_reopen(task, item, expected_version, reason)
        tx.requirements.reopen_requirement(item)
        tx.audit.record(task.project_id, actor.id, 'requirement.reopened', item.id,
                        {'task_id': task.id, 'version': expected_version + 1, 'reason': reason})
        return replace(item, status=RequirementStatus.ACTIVE,
                       version=item.version + 1, summary=None)

    def manage_requirement(self, actor: Actor, task_id: str, action: str, entity_id: str | None = None,
                           expected_version: int | None = None, changes: dict | None = None,
                           reason: str = '', request_id: str | None = None):
        changes = changes or {}
        validate_crud(action, entity_id, expected_version, changes, reason)
        if set(changes) - {'text', 'status', 'summary'}:
            raise ProductError('Requirement changes support text, status and summary.')
        if 'text' in changes and (not isinstance(changes['text'], str) or not changes['text'].strip()):
            raise ProductError('Requirement text must be a non-empty string.')
        if request_id is not None and (action != 'create' or not request_id or len(request_id) > 128):
            raise ProductError('A bounded request_id is accepted only for create.')
        transaction = self.uow.read if action in ('list', 'get') else self.uow.write
        with transaction() as tx:
            task = tx.workspaces.get_task(task_id)
            if task is None:
                raise ProductError('Task not found.', 'not_found')
            if action == 'list':
                return [] if task.status == TaskStatus.DELETED else tx.requirements.task_requirements(task_id)
            if action == 'get':
                item = tx.requirements.get_requirement(entity_id, task_id)
                if item is None:
                    raise ProductError('Requirement outside this Task.', 'not_found')
                return {**asdict(item), 'history': tx.requirements.versions(item.id)}
            if task.status == TaskStatus.DELETED:
                raise Conflict('Deleted Tasks cannot be changed.')
            if action == 'create':
                if (not changes.get('text') or changes.get('status', 'active') != 'active'
                        or changes.get('summary') is not None):
                    raise ProductError('New Requirements require text and start active without a summary.')
                previous = tx.requirements.web_requirement(task.project_id, request_id) if request_id else None
                if previous:
                    original = tx.requirements.versions(previous.id)[0]['text']
                    if previous.task_id != task.id or original != changes['text']:
                        raise Conflict('request_id was reused for a different Requirement.')
                    return previous
                if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                    raise Conflict('This Task no longer accepts Requirements.')
                item = Requirement(_id('requirement'), task.project_id, task.id, changes['text'],
                                   RequirementStatus.ACTIVE, 1, None)
                tx.requirements.create_requirement(item, None, request_id)
                tx.audit.record(task.project_id, actor.id, 'requirement.submitted', item.id,
                                {'task_id': task.id, 'version': 1})
                return item
            item = tx.requirements.get_requirement(entity_id, task_id)
            if item is None:
                raise ProductError('Requirement outside this Task.', 'not_found')
            if item.status == RequirementStatus.DELETED or item.version != expected_version:
                raise Conflict('Requirement version is stale or the Requirement is deleted.')
            target = 'deleted' if action == 'delete' else changes.get('status', item.status)
            if target not in ('active', 'archived') and action != 'delete':
                raise ProductError('Requirement status must be active or archived; use delete for soft deletion.')
            summary = None if target == 'active' else changes.get('summary', item.summary)
            if target == 'active' and changes.get('summary') is not None:
                raise ProductError('Active Requirements do not have a completion summary.')
            if target == 'archived' and (not isinstance(summary, str) or not summary.strip()):
                raise ProductError('An archived Requirement requires a completion summary.')
            if target != item.status and target == 'active':
                check_reopen(task, item, expected_version, reason)
            if target != item.status and target == 'archived':
                check_archive(task, item, expected_version, summary)
            changed = replace(item, text=changes.get('text', item.text), status=RequirementStatus(target),
                              summary=summary, version=item.version + 1)
            tx.requirements.update_requirement(changed, expected_version)
            if target != item.status and target in ('archived', 'deleted'):
                for rule_id in tx.requirements.linked_live_rule_ids(item.id):
                    tx.knowledge.deprecate_rule(tx.knowledge.get_rule(rule_id))
                if target == 'archived' and not tx.requirements.active_requirements(task.id):
                    tx.workspaces.complete_task(task.id)
                    tx.knowledge.deprecate_task_rules(task.id)
                    tx.audit.record(task.project_id, actor.id, 'task.completed', task.id,
                                    {'last_requirement_id': item.id})
            event = ('requirement.deleted' if action == 'delete' else
                     'requirement.reopened' if target != item.status and target == 'active' else
                     'requirement.archived' if target != item.status and target == 'archived' else 'requirement.updated')
            tx.audit.record(task.project_id, actor.id, event, item.id,
                {'task_id': task.id, 'version': changed.version, 'changes': changes, 'reason': reason})
            return changed

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
        for rule_id in tx.requirements.linked_live_rule_ids(item.id):
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
