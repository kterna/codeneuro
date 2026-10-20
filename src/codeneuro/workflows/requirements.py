"""Project requirements, explicit overall acceptance and immutable history."""
from dataclasses import asdict, replace
from ..modules.tasks import (Conflict, ProductError, Requirement, RequirementStatus,
                            validate_crud, validate_page, validate_text_changes,
                            require_open, ready_for_acceptance)
from .common import _id, _now, replay, history_page, page_cursor, cursor_id
from .workspaces import Workspaces


class Requirements(Workspaces):
    def manage_requirement(self, actor, project_id, action, entity_id=None, expected_version=None,
                           changes=None, reason='', request_id=None, *, statuses=None, cursor=None,
                           limit=None, history_cursor=None, history_limit=20, source=None):
        changes = changes or {}
        validate_crud(action, entity_id, expected_version, changes, reason)
        if action != 'list' and any(value is not None for value in (statuses, cursor, limit)):
            raise ProductError('statuses, cursor and limit apply only to list.')
        if action != 'create' and request_id is not None:
            raise ProductError('request_id applies only to create.')
        if set(changes) - {'title', 'text', 'acceptance_criteria', 'status', 'completion_summary', 'archived'}:
            raise ProductError('Unsupported Requirement changes.')
        validate_text_changes(changes, ('title', 'text', 'acceptance_criteria', 'completion_summary'))
        transaction = self.uow.read if action in ('get', 'list') else self.uow.write
        with transaction() as tx:
            tx.workspaces.project_revision(project_id)
            if action == 'list':
                size = 20 if limit is None else limit
                validate_page(statuses, cursor, size, set(RequirementStatus))
                after = cursor_id(cursor, 'requirements', project_id, statuses=statuses)
                rows = tx.requirements.project_requirements(project_id, statuses=statuses, cursor=after, limit=size + 1)
                progress = tx.requirements.progress([item.id for item in rows[:size]])
                return {'items': [{**{key: getattr(item, key) for key in ('id', 'project_id', 'status', 'version', 'archived_at')},
                    'title': item.title[:200], 'text': item.text[:200],
                    'truncated': len(item.title) > 200 or len(item.text) > 200,
                    'progress': progress.get(item.id, {'total': 0, 'completed': 0})} for item in rows[:size]],
                    'next_cursor': page_cursor(rows[size - 1].id, 'requirements', project_id, statuses=statuses)
                        if len(rows) > size else None}
            if action == 'create':
                if set(changes) - {'title', 'text', 'acceptance_criteria', 'status'}:
                    raise ProductError('New Requirements accept title, text, acceptance_criteria and draft/active status.')
                fingerprint, previous = replay(tx, project_id, 'requirement.create', request_id, changes)
                if previous:
                    return Requirement(**previous)
                if not changes.get('title', '').strip() or not changes.get('text', '').strip():
                    raise ProductError('Requirement title and text are required.')
                status = changes.get('status', 'active')
                if status not in ('draft', 'active'):
                    raise ProductError('New Requirements start as draft or active.')
                item = Requirement(_id('requirement'), project_id, changes['title'], changes['text'],
                    RequirementStatus(status), original_text=changes['text'],
                    acceptance_criteria=changes.get('acceptance_criteria', ''))
                tx.requirements.create_requirement(item)
                tx.workspaces.record_request(project_id, 'requirement.create', request_id, fingerprint, asdict(item))
                tx.audit.record(project_id, actor.id, 'requirement.created', item.id,
                                {'source': self._source(tx, actor, project_id, source)})
                return item
            item = tx.requirements.get_requirement(entity_id, project_id)
            if not item:
                raise ProductError('Requirement not found in this project.', 'not_found')
            if action == 'get':
                return {**asdict(item), 'progress': tx.requirements.progress([item.id]).get(item.id, {'total': 0, 'completed': 0}),
                    **history_page(lambda c, n: tx.requirements.versions(item.id, c, n), history_cursor, history_limit)}
            if item.version != expected_version or item.deleted_at:
                raise Conflict('Requirement version is stale or the Requirement is deleted.')
            children = tx.workspaces.list_tasks(project_id, requirement_id=item.id)
            now = _now()
            if action == 'update' and set(changes) == {'archived'}:
                changed = replace(item, archived_at=now if changes['archived'] else None, version=item.version + 1)
            else:
                require_open(item)
                if 'archived' in changes:
                    raise ProductError('Archive/restore separately from business edits.')
                if action == 'delete' and children:
                    raise Conflict('Handle the remaining Tasks explicitly before deleting their Requirement.')
                target = changes.get('status', item.status)
                scope_changed = any(key in changes and changes[key] != getattr(item, key)
                                    for key in ('text', 'acceptance_criteria'))
                transitions = {'draft': {'active'}, 'active': {'accepting'},
                               'accepting': {'active', 'completed'}, 'completed': {'active'}}
                if target != item.status and target not in transitions[item.status]:
                    raise Conflict('Unsupported Requirement transition.')
                if item.status == 'completed' and scope_changed and target != 'active':
                    raise Conflict('Reopen this Requirement before changing its accepted scope.')
                if scope_changed and item.status == 'accepting':
                    if target == 'completed':
                        raise Conflict('Do not change the scope while accepting it; review the new version first.')
                    target = RequirementStatus.ACTIVE
                completing = target == 'completed' and item.status != 'completed'
                if target in ('accepting', 'completed') and target != item.status and not ready_for_acceptance(children):
                    raise Conflict('At least one Task is required and every remaining Task must be verified completed.')
                if completing and not changes.get('completion_summary', '').strip():
                    raise ProductError('Overall acceptance needs completion_summary and a reason citing user confirmation.')
                if not completing and 'completion_summary' in changes:
                    raise ProductError('completion_summary applies only to overall acceptance.')
                if 'text' in changes and not changes['text'].strip():
                    raise ProductError('Requirement text cannot be empty.')
                changed = replace(item, title=changes.get('title', item.title), text=changes.get('text', item.text),
                    acceptance_criteria=changes.get('acceptance_criteria', item.acceptance_criteria),
                    status=RequirementStatus(target), version=item.version + 1,
                    completion_summary=changes['completion_summary'] if completing else
                        None if item.status == 'completed' and target == 'active' else item.completion_summary,
                    deleted_at=now if action == 'delete' else item.deleted_at)
            tx.requirements.update_requirement(changed, expected_version)
            if (changed.status == 'completed' and item.status != 'completed') or changed.deleted_at or changed.archived_at:
                for task in children:
                    tx.knowledge.deprecate_task_rules(task.id)
            tx.audit.record(project_id, actor.id, 'requirement.deleted' if action == 'delete' else 'requirement.updated', item.id,
                {'from': item.status, 'to': changed.status, 'version': changed.version, 'reason': reason,
                 'changes': changes, 'source': self._source(tx, actor, project_id, source)})
            return changed
