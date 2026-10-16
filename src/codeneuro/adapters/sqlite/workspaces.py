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

    def delete_project(self, project_id):
        # Clear origin_rule_id self-referential foreign keys first
        self.c.execute(s.rules.update().where(s.rules.c.project_id == project_id).values(origin_rule_id=None))
        # All predicates refer to parents, which remain until their children are removed.
        rules = sa.select(s.rules.c.id).where(s.rules.c.project_id == project_id)
        requirements = sa.select(s.requirements.c.id).where(s.requirements.c.project_id == project_id)
        sessions = sa.select(s.sessions.c.id).where(s.sessions.c.project_id == project_id)
        deliveries = sa.select(s.deliveries.c.id).where(s.deliveries.c.session_id.in_(sessions))
        indirect = {
            'agent_rule_state': s.agent_rule_state.c.rule_id.in_(rules),
            'rule_observations': s.rule_observations.c.rule_id.in_(rules),
            'requirement_versions': s.requirement_versions.c.requirement_id.in_(requirements),
            'requirement_rule_links': s.requirement_rule_links.c.rule_id.in_(rules),
            'rule_versions': s.rule_versions.c.rule_id.in_(rules),
            'deliveries': s.deliveries.c.session_id.in_(sessions),
            'delivery_rules': s.delivery_rules.c.delivery_id.in_(deliveries),
            'delivery_requirements': s.delivery_requirements.c.delivery_id.in_(deliveries),
            'delivery_findings': s.delivery_findings.c.delivery_id.in_(deliveries),
            'feedback': s.feedback.c.delivery_id.in_(deliveries),
            'projects': s.projects.c.id == project_id,
        }
        for table in reversed(s.metadata.sorted_tables):
            predicate = (table.c.project_id == project_id if 'project_id' in table.c
                         else indirect[table.name])
            self.c.execute(table.delete().where(predicate))

    def transition_task(self, task, status):
        result = self.c.execute(s.tasks.update().where(
            s.tasks.c.id == task.id, s.tasks.c.revision == task.revision).values(
            status=status, paused_from=None, revision=s.tasks.c.revision + 1))
        if result.rowcount != 1:
            raise Conflict('Task changed before this transition.')

    def list_projects(self):
        return [dict(r) for r in self.c.execute(sa.select(s.projects).order_by(s.projects.c.id)).mappings()]

    def get_task(self, task_id, project_id=None):
        statement = sa.select(s.tasks).where(s.tasks.c.id == task_id)
        if project_id is not None:
            statement = statement.where(s.tasks.c.project_id == project_id)
        return _task(self._one(statement))

    def list_tasks(self, project_id):
        return [_task(r) for r in self.c.execute(sa.select(s.tasks).where(
            s.tasks.c.project_id == project_id, s.tasks.c.status != TaskStatus.DELETED).order_by(s.tasks.c.id)).mappings()]

    def create_task(self, task):
        self.c.execute(s.tasks.insert().values(id=task.id, project_id=task.project_id,
            title=task.title, description=task.description, status=task.status,
            revision=task.revision, paused_from=task.paused_from))

    def update_task(self, task, expected_version):
        result = self.c.execute(s.tasks.update().where(
            s.tasks.c.id == task.id, s.tasks.c.revision == expected_version).values(
            title=task.title, description=task.description, status=task.status,
            paused_from=task.paused_from, revision=task.revision))
        if result.rowcount != 1:
            raise Conflict('Task version is stale.')

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
