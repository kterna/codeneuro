"""Project/task operations coordinated in short, versioned transactions."""
from dataclasses import asdict, replace
import hashlib
import re

from ..modules.tasks import (Conflict, ProductError, Task, TaskStatus, RequirementStatus,
                            validate_crud, validate_page, validate_text_changes,
                            require_open, require_working, ready_for_acceptance)
from ..modules.workspaces import Worktree
from ..ports import UnitOfWork
from .common import _id, _now, replay, history_page, page_cursor, cursor_id


class Workspaces:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    @staticmethod
    def _task(tx, task_id, project_id=None, *, writable=False, allow_completed=False):
        task = tx.workspaces.get_task(task_id, project_id)
        if not task or task.deleted_at:
            raise ProductError('Task not found in the selected project.', 'not_found')
        parent = tx.requirements.get_requirement(task.requirement_id, task.project_id)
        if not parent or parent.deleted_at:
            raise ProductError('Parent Requirement not found.', 'not_found')
        if writable:
            require_working(task, parent, allow_completed=allow_completed)
        return task, parent

    @staticmethod
    def _source(tx, actor, project_id, source=None):
        source = dict(source or {})
        bounds = {'workspace': 4096, 'machine_name': 255, 'platform': 16,
                  'repo_identity': 128, 'git_branch': 255}
        if set(source) - bounds.keys():
            raise ProductError('Unknown source field.')
        for name, value in source.items():
            if not isinstance(value, str) or len(value) > bounds[name] or '\x00' in value or '\n' in value:
                raise ProductError(f'Invalid bounded source field: {name}.')
        if 'platform' in source:
            source['platform'] = {'win32': 'windows', 'cygwin': 'windows', 'darwin': 'macos'}.get(
                source['platform'].lower(), source['platform'].lower())
            if source['platform'] not in ('windows', 'linux', 'macos', 'unknown'):
                raise ProductError('source.platform must be windows, linux, macos or unknown.')
        if all(source.get(name) for name in ('workspace', 'machine_name', 'platform')):
            path = source['workspace'].casefold() if source['platform'] == 'windows' else source['workspace']
            key = '\0'.join((project_id, actor.id, source['machine_name'].casefold(), source['platform'], path))
            wid = 'wt_' + hashlib.sha256(key.encode()).hexdigest()[:32]
            tx.workspaces.register_worktree(Worktree(wid, project_id, actor.id, source['workspace'],
                source['machine_name'], source['platform'], source.get('repo_identity'), source.get('git_branch', '')))
            source['worktree_id'] = wid
        return {**source, 'actor_id': actor.id}

    def register_project(self, actor, project_id, name):
        if actor.role != 'human':
            raise ProductError('Only a human administrator may register a project.', 'forbidden')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', project_id):
            raise ProductError('Project ID must contain 1–128 letters, digits, _ or - and start with a letter or digit.')
        if not name.strip() or len(name) > 500:
            raise ProductError('Project name must contain 1–500 characters.')
        with self.uow.write() as tx:
            if any(item['id'] == project_id for item in tx.workspaces.list_projects()):
                raise Conflict('Project ID already exists.')
            tx.workspaces.create_project(project_id, name)
            tx.audit.record(project_id, actor.id, 'project.created', project_id, {})
        return {'id': project_id, 'name': name}

    def delete_project(self, actor, project_id):
        if actor.role != 'human':
            raise ProductError('Only a human administrator may delete a project.', 'forbidden')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            tx.workspaces.delete_project(project_id)
        return {'deleted': True, 'id': project_id}

    def list_projects(self, actor):
        with self.uow.read() as tx:
            return tx.workspaces.list_projects()

    def list_tasks(self, actor, project_id, requirement_id=None):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            return tx.workspaces.list_tasks(project_id, requirement_id=requirement_id)

    def create_task(self, actor, project_id, requirement_id, title, description='', initial_status='active',
                    acceptance_criteria='', request_id=None):
        return self.manage_task(actor, project_id, 'create', changes={'title': title, 'description': description,
            'status': initial_status, 'acceptance_criteria': acceptance_criteria},
            requirement_id=requirement_id, request_id=request_id)

    @staticmethod
    def _touch_parent(tx, parent, *, completed=False, invalidate=False):
        status = parent.status
        children = tx.workspaces.list_tasks(parent.project_id, requirement_id=parent.id)
        if status == 'accepting' and (invalidate or not ready_for_acceptance(children)):
            status = RequirementStatus.ACTIVE
        elif status == 'active' and completed and ready_for_acceptance(children):
            status = RequirementStatus.ACCEPTING
        changed = replace(parent, status=status, version=parent.version + 1)
        tx.requirements.update_requirement(changed, parent.version)
        return changed

    def manage_task(self, actor, project_id, action, entity_id=None, expected_version=None,
                    changes=None, reason='', *, requirement_id=None, statuses=None, cursor=None, limit=None,
                    request_id=None, history_cursor=None, history_limit=20, source=None):
        changes = changes or {}
        validate_crud(action, entity_id, expected_version, changes, reason)
        if action != 'list' and any(value is not None for value in (statuses, cursor, limit)):
            raise ProductError('statuses, cursor and limit apply only to list.')
        if action not in ('create', 'list') and requirement_id is not None:
            raise ProductError('requirement_id applies only to create/list; tasks cannot be moved by update.')
        if action != 'create' and request_id is not None:
            raise ProductError('request_id applies only to create.')
        allowed = {'title', 'description', 'acceptance_criteria', 'status', 'archived',
                   'verification_summary', 'verification_report_ids'}
        if set(changes) - allowed:
            raise ProductError('Unsupported Task changes.')
        validate_text_changes(changes, ('title', 'description', 'acceptance_criteria', 'verification_summary'))
        transaction = self.uow.read if action in ('list', 'get') else self.uow.write
        with transaction() as tx:
            tx.workspaces.project_revision(project_id)
            if action == 'list':
                size = 20 if limit is None else limit
                validate_page(statuses, cursor, size, set(TaskStatus))
                if requirement_id and not tx.requirements.get_requirement(requirement_id, project_id):
                    raise ProductError('Requirement not found in this project.', 'not_found')
                after = cursor_id(cursor, 'tasks', project_id, requirement_id, statuses)
                rows = tx.workspaces.list_tasks(project_id, requirement_id=requirement_id,
                    statuses=statuses, cursor=after, limit=size + 1)
                return {'items': [{**{key: getattr(task, key) for key in
                    ('id', 'project_id', 'requirement_id', 'status', 'version', 'archived_at')},
                    'title': task.title[:200], 'description': task.description[:200],
                    'truncated': len(task.title) > 200 or len(task.description) > 200} for task in rows[:size]],
                    'next_cursor': page_cursor(rows[size - 1].id, 'tasks', project_id, requirement_id, statuses)
                        if len(rows) > size else None}
            if action == 'create':
                if set(changes) - {'title', 'description', 'acceptance_criteria', 'status'}:
                    raise ProductError('New Tasks accept title, description, acceptance_criteria and draft/active status.')
                parent = tx.requirements.get_requirement(requirement_id, project_id) if requirement_id else None
                if not parent:
                    raise ProductError('Select a parent Requirement in this project.', 'not_found')
                fingerprint, previous = replay(tx, project_id, 'task.create', request_id,
                                               {'requirement_id': requirement_id, 'changes': changes})
                if previous:
                    return Task(**{**previous, 'verification_report_ids': tuple(previous['verification_report_ids'])})
                require_open(parent)
                status = changes.get('status', 'active')
                if parent.status == 'completed':
                    raise Conflict('Reopen the completed Requirement before adding a Task.')
                if status not in ('draft', 'active') or (parent.status == 'draft' and status != 'draft'):
                    raise Conflict('Create draft/active Tasks; a draft Requirement only accepts draft Tasks.')
                if not changes.get('title', '').strip():
                    raise ProductError('Task title is required.')
                task = Task(_id('task'), project_id, parent.id, changes['title'], changes.get('description', ''),
                    TaskStatus(status), acceptance_criteria=changes.get('acceptance_criteria', ''))
                tx.workspaces.create_task(task)
                self._touch_parent(tx, parent, invalidate=True)
                tx.workspaces.record_request(project_id, 'task.create', request_id, fingerprint, asdict(task))
                provenance = self._source(tx, actor, project_id, source)
                tx.audit.record(project_id, actor.id, 'task.created', task.id,
                                {'requirement_id': parent.id, 'source': provenance})
                return task
            task = tx.workspaces.get_task(entity_id, project_id)
            if not task:
                raise ProductError('Task not found in this project.', 'not_found')
            if action == 'get':
                return {**asdict(task), **history_page(lambda c, n: tx.workspaces.task_versions(task.id, c, n),
                                                      history_cursor, history_limit)}
            if task.version != expected_version or task.deleted_at:
                raise Conflict('Task version is stale or the Task is deleted.')
            parent = tx.requirements.get_requirement(task.requirement_id, project_id)
            require_open(parent)
            now = _now()
            if action == 'update' and set(changes) == {'archived'}:
                changed = replace(task, archived_at=now if changes['archived'] else None, version=task.version + 1)
            else:
                require_open(task)
                if parent.status == 'completed':
                    raise Conflict('Reopen the completed Requirement before changing its Tasks.')
                if 'archived' in changes:
                    raise ProductError('Archive/restore separately from business edits.')
                target = changes.get('status', task.status)
                transitions = {'draft': {'active'}, 'active': {'testing', 'paused'},
                    'testing': {'active', 'completed', 'paused'}, 'paused': {task.paused_from}, 'completed': {'active'}}
                if target != task.status and target not in transitions[task.status]:
                    raise Conflict('Unsupported Task transition; verification must pass through testing.')
                if target != 'draft' and parent.status == 'draft':
                    raise Conflict('Activate the parent Requirement before starting work.')
                scope_changed = any(key in changes and changes[key] != getattr(task, key)
                                    for key in ('description', 'acceptance_criteria'))
                if scope_changed and task.status in ('testing', 'completed') and target != 'active':
                    raise Conflict('Return the Task to active when changing its verified scope.')
                completing = target == 'completed' and task.status != 'completed'
                if not completing and any(key in changes for key in ('verification_summary', 'verification_report_ids')):
                    raise ProductError('Verification results apply only to testing → completed.')
                reports = tuple(changes.get('verification_report_ids', ()))
                if completing:
                    if not changes.get('verification_summary', '').strip():
                        raise ProductError('An explicit verification_summary is required to complete a Task.')
                    if len(set(reports)) != len(reports) or any(not isinstance(rid, str) or not rid for rid in reports):
                        raise ProductError('Use distinct verification report IDs.')
                    for rid in reports:
                        report = tx.governance.test_report(rid)
                        if not report or report.task_id != task.id or report.project_id != project_id:
                            raise ProductError('Verification report is outside this Task.', 'not_found')
                        if report.exit_code != 0 or any(case['status'] == 'failed' for case in report.test_cases):
                            raise Conflict('A failed report cannot support Task completion.')
                reopened = task.status == 'completed' and target == 'active'
                changed = replace(task, title=changes.get('title', task.title),
                    description=changes.get('description', task.description),
                    acceptance_criteria=changes.get('acceptance_criteria', task.acceptance_criteria),
                    status=TaskStatus(target), version=task.version + 1,
                    paused_from=(task.paused_from if task.status == 'paused' else task.status) if target == 'paused' else None,
                    verification_summary=changes['verification_summary'] if completing else None if reopened else task.verification_summary,
                    verification_report_ids=reports if completing else () if reopened else task.verification_report_ids,
                    deleted_at=now if action == 'delete' else task.deleted_at)
            tx.workspaces.update_task(changed, expected_version)
            if changed.deleted_at or (changed.archived_at and not task.archived_at):
                tx.knowledge.deprecate_task_rules(task.id)
            self._touch_parent(tx, parent, completed=task.status != 'completed' and changed.status == 'completed',
                               invalidate=any(key in changes for key in ('description', 'acceptance_criteria')))
            tx.audit.record(project_id, actor.id, 'task.deleted' if action == 'delete' else 'task.updated', task.id,
                {'from': task.status, 'to': changed.status, 'version': changed.version, 'reason': reason,
                 'changes': changes, 'source': self._source(tx, actor, project_id, source)})
            return changed
