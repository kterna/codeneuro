"""Authenticated caller and pinned agent session identities."""
from dataclasses import dataclass

from .tasks import ProductError


@dataclass(frozen=True)
class Actor:
    id: str
    project_ids: frozenset[str]
    role: str = 'agent'

    def authorize(self, project_id: str):
        if project_id not in self.project_ids:
            raise ProductError('Project is outside the authenticated identity.', 'forbidden')


@dataclass(frozen=True)
class Worktree:
    id: str
    project_id: str
    actor_id: str
    workspace: str
    machine_name: str
    platform: str
    repo_identity: str | None
    git_branch: str


@dataclass(frozen=True)
class Session:
    id: str
    project_id: str
    task_id: str | None
    workspace: str
    worktree_id: str
    actor_id: str
    debug: bool
    state: str
    knowledge_revision: int

    def owned_by(self, actor: Actor):
        actor.authorize(self.project_id)
        if self.actor_id != actor.id:
            raise ProductError('Session belongs to a different actor.', 'forbidden')
        if self.state != 'active':
            raise ProductError('Session is closed.', 'conflict')
