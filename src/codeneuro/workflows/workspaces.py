"""Workspaces application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

import hashlib

from ..modules.tasks import Conflict, ProductError, Task, TaskStatus
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
        with self.uow.write() as tx:
            tx.workspaces.create_project(project_id, name)
            tx.audit.record(project_id, actor.id, 'project.created', project_id, {})
        return {'id': project_id, 'name': name}

    def list_projects(self, actor: Actor):
        with self.uow.read() as tx:
            return tx.workspaces.list_projects()

    def list_tasks(self, actor: Actor, project_id: str):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            return tx.workspaces.list_tasks(project_id)

    def create_task(self, actor: Actor, project_id: str, title: str, description: str = ''):
        if not title.strip():
            raise ProductError('Task title is required.')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            task = Task(_id('task'), project_id, title, description, TaskStatus.ACTIVE, 0)
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

    def start_session(self, actor: Actor, project_id: str, workspace: str,
                      task_id: str | None = None, agent_client: str = 'MCP', debug: bool = False,
                      *, machine_name: str = 'not_attested', platform: str = 'unknown',
                      repo_identity: str | None = None, git_branch: str = ''):
        if (not isinstance(workspace, str) or not workspace.strip() or len(workspace) > 4096
                or '\x00' in workspace or '\n' in workspace or not agent_client.strip()
                or not machine_name or len(machine_name) > 255
                or platform not in ('windows', 'linux', 'macos', 'unknown')
                or len(git_branch) > 255 or (repo_identity and len(repo_identity) > 128)):
            raise ProductError('A bounded client-attested worktree identity is required.')
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
