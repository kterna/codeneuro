"""Task and Requirement invariants; independent of transport and persistence."""
from dataclasses import dataclass
from enum import StrEnum


class ProductError(ValueError):
    def __init__(self, message: str, code: str = 'invalid_request'):
        super().__init__(message)
        self.code = code


class Conflict(ProductError):
    def __init__(self, message: str):
        super().__init__(message, 'conflict')


class TaskStatus(StrEnum):
    DRAFT = 'draft'
    ACTIVE = 'active'
    TESTING = 'testing'
    PAUSED = 'paused'
    RELEASED = 'released'
    ARCHIVED = 'archived'


class RequirementStatus(StrEnum):
    ACTIVE = 'active'
    ARCHIVED = 'archived'


@dataclass(frozen=True)
class Task:
    id: str
    project_id: str
    title: str
    description: str
    status: TaskStatus
    revision: int
    paused_from: TaskStatus | None = None


@dataclass(frozen=True)
class Requirement:
    id: str
    project_id: str
    task_id: str
    text: str
    status: RequirementStatus
    version: int
    summary: str | None


def check_archive(task: Task, requirement: Requirement, expected_version: int, summary: str):
    if requirement.task_id != task.id or requirement.project_id != task.project_id:
        raise ProductError('Requirement is outside the selected Task.', 'not_found')
    if not summary.strip():
        raise ProductError('A completion summary is required.')
    if requirement.status == RequirementStatus.ARCHIVED:
        if requirement.version == expected_version + 1 and requirement.summary == summary:
            return False  # Idempotent retry; no second Task completion.
        raise Conflict('Requirement was already archived with different input.')
    if requirement.version != expected_version:
        raise Conflict('Requirement version is stale.')
    if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
        raise Conflict('Only active/testing Tasks accept Requirement archival; paused/released must transition first.')
    return True
