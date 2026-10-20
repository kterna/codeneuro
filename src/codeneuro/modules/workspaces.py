"""Caller and optional worktree provenance; neither is authentication."""
from dataclasses import dataclass


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
