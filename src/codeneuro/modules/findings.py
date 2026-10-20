"""Agent observations are not approved project-wide contracts."""
from dataclasses import dataclass

from .knowledge import Priority


@dataclass(frozen=True)
class Finding:
    id: str
    project_id: str
    task_id: str
    target_path: str | None
    text: str
    priority: Priority
    version: int = 1
    status: str = 'pending_review'
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class Issue:
    id: str
    project_id: str
    task_id: str | None
    issue_type: str
    title: str
    description: str
    file_path: str | None
    related_rule_ids: tuple[str, ...]
    suggested_action: str
    related_rule_versions: tuple[tuple[str, int], ...] = ()
