"""Workspaces application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from ..modules.tasks import Conflict, ProductError, Task, TaskStatus, validate_crud
from ..modules.workspaces import Actor, Session, Worktree
from ..ports import UnitOfWork
from .common import _id


class Workspaces:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    @staticmethod
    def _session(tx, actor: Actor, session_id: str) -> Session:
        session = tx.workspaces.get_session(session_id)
        if session is None:
            raise ProductError('Session not found.', 'not_found')
        session.require_active()
        return session

    def register_project(self, actor: Actor, project_id: str, name: str):
        if actor.role != 'human' or not name.strip():
            raise ProductError('Only a human administrator may register a project.', 'forbidden')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', project_id):
            raise ProductError('Project ID must start with a letter or digit and contain only letters, digits, _ or - (1–128 characters).')
        if len(name.strip()) > 500:
            raise ProductError('Project name must not exceed 500 characters.')
        with self.uow.write() as tx:
            if any(item['id'] == project_id for item in tx.workspaces.list_projects()):
                raise Conflict('Project ID already exists. Choose another ID.')
            tx.workspaces.create_project(project_id, name)
            tx.audit.record(project_id, actor.id, 'project.created', project_id, {})
        return {'id': project_id, 'name': name}

    def delete_project(self, actor: Actor, project_id: str):
        if actor.role != 'human':
            raise ProductError('Only a human administrator may delete a project.', 'forbidden')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            tx.workspaces.delete_project(project_id)
        return {'deleted': True, 'id': project_id}

    def list_projects(self, actor: Actor):
        with self.uow.read() as tx:
            return tx.workspaces.list_projects()

    def list_tasks(self, actor: Actor, project_id: str):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            return tx.workspaces.list_tasks(project_id)

    def list_task_page(self, actor: Actor, project_id: str, *, statuses: tuple[str, ...] | None = None,
                       cursor: str | None = None, limit: int = 20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProductError('Task list limit must be 1–100.')
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 128):
            raise ProductError('Task list cursor must be a Task ID of 1–128 characters.')
        allowed = {status.value for status in TaskStatus if status != TaskStatus.DELETED}
        if statuses is not None and (not statuses or len(set(statuses)) != len(statuses)
                                     or any(status not in allowed for status in statuses)):
            raise ProductError('Task list statuses must be distinct non-deleted Task states; omit for all states.')
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            tasks = tx.workspaces.list_tasks(project_id, statuses=statuses, cursor=cursor, limit=limit + 1)
        return {'items': [{'id': task.id, 'title': task.title[:200], 'description': task.description[:200],
                           'status': task.status, 'version': task.revision,
                           'truncated': len(task.title) > 200 or len(task.description) > 200}
                          for task in tasks[:limit]],
                'next_cursor': tasks[limit - 1].id if len(tasks) > limit else None}

    def create_task(self, actor: Actor, project_id: str, title: str, description: str = '',
                    initial_status: str = 'active'):
        if not title.strip():
            raise ProductError('Task title is required.')
        if initial_status not in ('draft', 'active'):
            raise ProductError('New Tasks must start as draft or active.')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            task = Task(_id('task'), project_id, title, description, TaskStatus(initial_status), 0)
            tx.workspaces.create_task(task)
            tx.audit.record(project_id, actor.id, 'task.created', task.id, {})
            return task

    def pause_task(self, actor: Actor, project_id: str, task_id: str,
                   expected_revision: int, reason: str):
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Human review and a reason are required to pause a Task.', 'forbidden')
        with self.uow.write() as tx:
            task = tx.workspaces.get_task(task_id, project_id)
            if task is None:
                raise ProductError('Task not found.', 'not_found')
            if task.revision != expected_revision or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Only current active/testing Tasks can be paused.')
            tx.workspaces.pause_task(task)
            tx.audit.record(project_id, actor.id, 'task.paused', task_id, {'reason': reason})
            return tx.workspaces.get_task(task_id, project_id)

    def resume_task(self, actor: Actor, project_id: str, task_id: str,
                    expected_revision: int, reason: str):
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Human review and a reason are required to resume a Task.', 'forbidden')
        with self.uow.write() as tx:
            task = tx.workspaces.get_task(task_id, project_id)
            if task is None:
                raise ProductError('Task not found.', 'not_found')
            if (task.revision != expected_revision or task.status != TaskStatus.PAUSED
                    or task.paused_from not in (TaskStatus.ACTIVE, TaskStatus.TESTING)):
                raise Conflict('Only a current paused Task can be resumed.')
            tx.workspaces.resume_task(task)
            tx.audit.record(project_id, actor.id, 'task.resumed', task_id, {'reason': reason})
            return tx.workspaces.get_task(task_id, project_id)

    def transition_task(self, actor: Actor, project_id: str, task_id: str,
                        expected_revision: int, status: str, reason: str):
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Human review and a reason are required.', 'forbidden')
        return self.manage_task(actor, project_id, 'update', task_id, expected_revision,
                                {'status': status}, reason)

    def manage_task(self, actor: Actor, project_id: str, action: str, entity_id: str | None = None,
                    expected_version: int | None = None, changes: dict | None = None, reason: str = '',
                    *, statuses: tuple[str, ...] | None = None, cursor: str | None = None,
                    limit: int | None = None):
        changes = changes or {}
        validate_crud(action, entity_id, expected_version, changes, reason)
        if action != 'list' and any(value is not None for value in (statuses, cursor, limit)):
            raise ProductError('statuses, cursor and limit apply only to Task list.')
        if set(changes) - {'title', 'description', 'status'}:
            raise ProductError('Task changes support title, description and status.')
        if ('title' in changes and (not isinstance(changes['title'], str) or not changes['title'].strip())
                or 'description' in changes and not isinstance(changes['description'], str)):
            raise ProductError('Task title must be non-empty and description must be a string.')
        if action == 'create':
            return self.create_task(actor, project_id, changes.get('title', ''),
                                    changes.get('description', ''), changes.get('status', 'active'))
        if action == 'list':
            return self.list_task_page(actor, project_id, statuses=statuses, cursor=cursor,
                                       limit=20 if limit is None else limit)
        transaction = self.uow.read if action == 'get' else self.uow.write
        with transaction() as tx:
            task = tx.workspaces.get_task(entity_id, project_id)
            if task is None:
                raise ProductError('Task not found.', 'not_found')
            if action == 'get':
                return task
            if task.revision != expected_version or task.status == TaskStatus.DELETED:
                raise Conflict('Task version is stale or the Task is deleted.')
            target = 'deleted' if action == 'delete' else changes.get('status', task.status)
            transitions = {
                'draft': {'active', 'archived'},
                'active': {'testing', 'paused', 'archived'},
                'testing': {'active', 'paused', 'released', 'archived'},
                'paused': {task.paused_from},
                'released': {'active', 'archived'},
                'archived': {'active', 'released'},
            }
            if action != 'delete' and target != task.status and target not in transitions[task.status]:
                raise Conflict('This Task transition is not allowed.')
            if target != task.status and target in ('released', 'archived') and tx.requirements.active_requirements(task.id):
                raise Conflict('Archive the active Requirements before completing or releasing this Task.')
            changed = replace(task, title=changes.get('title', task.title),
                description=changes.get('description', task.description), status=TaskStatus(target),
                paused_from=(task.paused_from if task.status == target else task.status) if target == 'paused' else None,
                revision=task.revision + 1)
            tx.workspaces.update_task(changed, expected_version)
            if target != task.status and target in ('released', 'archived', 'deleted'):
                tx.knowledge.deprecate_task_rules(task.id)
                changed = tx.workspaces.get_task(task.id, project_id)
            event = 'task.updated'
            if action == 'delete':
                event = 'task.deleted'
            elif target != task.status:
                event = ('task.reopened' if task.status == 'archived' and target == 'active' else
                         'task.paused' if target == 'paused' else
                         'task.resumed' if task.status == 'paused' else 'task.transitioned')
            tx.audit.record(project_id, actor.id, event, task.id,
                {'from': task.status, 'to': target, 'version': changed.revision, 'changes': changes, 'reason': reason})
            return changed

    def start_session(self, actor: Actor, project_id: str, workspace: str,
                      task_id: str | None = None, agent_client: str = 'MCP', debug: bool = False,
                      *, machine_name: str = 'not_attested', platform: str = 'unknown',
                      repo_identity: str | None = None, git_branch: str = ''):
        # 常见操作系统平台标识归一化
        platform_normalized = platform.lower().strip() if isinstance(platform, str) else 'unknown'
        platform_alias = {
            'win32': 'windows',
            'cygwin': 'windows',
            'darwin': 'macos',
        }
        platform = platform_alias.get(platform_normalized, platform_normalized)

        if not isinstance(workspace, str) or not workspace.strip() or len(workspace) > 4096 or '\x00' in workspace or '\n' in workspace:
            raise ProductError('A bounded client-attested worktree identity is required: workspace must be a non-empty string under 4096 characters without nulls or newlines.')
        if not isinstance(agent_client, str) or not agent_client.strip():
            raise ProductError('A bounded client-attested worktree identity is required: agent_client must be non-empty.')
        if not isinstance(machine_name, str) or not machine_name.strip() or len(machine_name) > 255:
            raise ProductError('A bounded client-attested worktree identity is required: machine_name must be a non-empty string under 255 characters.')
        if platform not in ('windows', 'linux', 'macos', 'unknown'):
            raise ProductError(f"A bounded client-attested worktree identity is required: platform must be one of ('windows', 'linux', 'macos', 'unknown'); got '{platform}'.")
        if not isinstance(git_branch, str) or len(git_branch) > 255:
            raise ProductError('A bounded client-attested worktree identity is required: git_branch exceeds maximum length of 255 characters.')
        if repo_identity and (not isinstance(repo_identity, str) or len(repo_identity) > 128):
            raise ProductError('A bounded client-attested worktree identity is required: repo_identity exceeds maximum length of 128 characters.')
        canonical = workspace.casefold() if platform == 'windows' else workspace
        key = '\0'.join((project_id, actor.id, machine_name.casefold(), platform, canonical))
        wid = 'wt_' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]
        worktree = Worktree(wid, project_id, actor.id, workspace,
                            machine_name, platform, repo_identity, git_branch)
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            if task_id:
                task = tx.workspaces.get_task(task_id, project_id)
                if task is None or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                    raise Conflict('A session can only bind an active/testing Task in its project.')
            tx.workspaces.register_worktree(worktree)
            session = Session(_id('session'), project_id, task_id, workspace, wid,
                              actor.id, debug, 'active', 0)
            tx.workspaces.create_session(session, agent_client)
            tx.audit.record(project_id, actor.id, 'session.started', session.id,
                            {'task_id': task_id, 'worktree_id': wid, 'identity': 'client_attested'})
            return session

    def end_session(self, actor: Actor, session_id: str):
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            tx.workspaces.close_session(session_id)
            tx.audit.record(session.project_id, actor.id, 'session.closed', session_id, {})
            return {'session_id': session_id, 'state': 'closed'}
