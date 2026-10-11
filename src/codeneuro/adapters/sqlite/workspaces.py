"""Feature-scoped SQLAlchemy Core repository; domain decisions live in workflows."""
from __future__ import annotations
import sqlalchemy as sa
from ...modules.tasks import Conflict, ProductError, TaskStatus
from . import schema as s
from .common import Repo, _task, _session, _worktree

class WorkspacesRepo(Repo):
    def project_revision(self, project_id):
        row = self._one(sa.select(s.projects.c.rule_revision).where(s.projects.c.id == project_id))
        if row is None:
            raise ProductError('Project not found.', 'not_found')
        return row['rule_revision']

    def create_project(self, project_id, name):
        self.c.execute(s.projects.insert().values(id=project_id, name=name, rule_revision=0))

    def list_projects(self):
        return [dict(r) for r in self.c.execute(sa.select(s.projects).order_by(s.projects.c.id)).mappings()]

    def get_task(self, task_id, project_id):
        return _task(self._one(sa.select(s.tasks).where(s.tasks.c.id == task_id,
                                                       s.tasks.c.project_id == project_id)))

    def list_tasks(self, project_id):
        return [_task(r) for r in self.c.execute(sa.select(s.tasks).where(
            s.tasks.c.project_id == project_id).order_by(s.tasks.c.id)).mappings()]

    def create_task(self, task):
        self.c.execute(s.tasks.insert().values(id=task.id, project_id=task.project_id,
            title=task.title, description=task.description, status=task.status,
            revision=task.revision, paused_from=task.paused_from))

    def complete_task(self, task_id):
        self.c.execute(s.tasks.update().where(s.tasks.c.id == task_id).values(
            status=TaskStatus.ARCHIVED, revision=s.tasks.c.revision + 1))

    def pause_task(self, task):
        result = self.c.execute(s.tasks.update().where(
            s.tasks.c.id == task.id, s.tasks.c.revision == task.revision,
            s.tasks.c.status == task.status).values(status=TaskStatus.PAUSED,
                paused_from=task.status, revision=s.tasks.c.revision + 1))
        if result.rowcount != 1:
            raise Conflict('Task changed before pause.')

    def resume_task(self, task):
        result = self.c.execute(s.tasks.update().where(
            s.tasks.c.id == task.id, s.tasks.c.revision == task.revision,
            s.tasks.c.status == TaskStatus.PAUSED).values(status=task.paused_from,
                paused_from=None, revision=s.tasks.c.revision + 1))
        if result.rowcount != 1:
            raise Conflict('Task changed before resume.')

    def get_session(self, session_id):
        return _session(self._one(sa.select(s.sessions).where(s.sessions.c.id == session_id)))

    def register_worktree(self, worktree):
        existing = self._one(sa.select(s.worktrees).where(s.worktrees.c.id == worktree.id))
        if existing:
            if (existing['project_id'] != worktree.project_id or
                existing['actor_id'] != worktree.actor_id or
                (existing['workspace'].casefold() if worktree.platform == 'windows' else existing['workspace']) !=
                (worktree.workspace.casefold() if worktree.platform == 'windows' else worktree.workspace) or
                existing['machine_name'].casefold() != worktree.machine_name.casefold() or
                existing['platform'] != worktree.platform or
                (existing['repo_identity'] and worktree.repo_identity and
                 existing['repo_identity'] != worktree.repo_identity)):
                raise Conflict('Worktree identity cannot be rebound.')
            self.c.execute(s.worktrees.update().where(s.worktrees.c.id == worktree.id).values(
                repo_identity=worktree.repo_identity or existing['repo_identity'],
                git_branch=worktree.git_branch))
        else:
            self.c.execute(s.worktrees.insert().values(**worktree.__dict__))

    def project_worktrees(self, project_id):
        return [_worktree(row) for row in self.c.execute(sa.select(s.worktrees).where(
            s.worktrees.c.project_id == project_id).order_by(s.worktrees.c.id)).mappings()]

    def create_session(self, session, agent_client):
        self.c.execute(s.sessions.insert().values(id=session.id, project_id=session.project_id,
            task_id=session.task_id, worktree_id=session.worktree_id,
            workspace=session.workspace, agent_client=agent_client,
            actor_id=session.actor_id, debug=session.debug, state=session.state,
            knowledge_revision=session.knowledge_revision))

    def close_session(self, session_id):
        self.c.execute(s.sessions.update().where(s.sessions.c.id == session_id).values(state='closed'))
