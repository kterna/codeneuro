"""Caller provenance and agent session metadata (not authenticated)."""
from dataclasses import dataclass

from .tasks import ProductError


@dataclass(frozen=True)
class Actor:
    id: str
    role: str = 'agent'


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

    def require_active(self):
        if self.state != 'active':
            raise ProductError('Session is closed.', 'conflict')
