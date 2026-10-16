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
    DELETED = 'deleted'


class RequirementStatus(StrEnum):
    ACTIVE = 'active'
    ARCHIVED = 'archived'
    DELETED = 'deleted'


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


def check_reopen(task: Task, requirement: Requirement, expected_version: int, reason: str):
    if requirement.task_id != task.id or requirement.project_id != task.project_id:
        raise ProductError('Requirement is outside the selected Task.', 'not_found')
    if not reason.strip():
        raise ProductError('A reason is required to reopen a Requirement.')
    if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
        raise Conflict('Reopen or resume the Task before reopening a Requirement.')
    if requirement.version != expected_version or requirement.status != RequirementStatus.ARCHIVED:
        raise Conflict('Only a current archived Requirement can be reopened.')


def validate_crud(action, entity_id, expected_version, changes, reason):
    if action not in ('create', 'list', 'get', 'update', 'delete'):
        raise ProductError('Use create, list, get, update or delete.')
    if action in ('get', 'update', 'delete'):
        if not entity_id:
            raise ProductError('id is required for get, update and delete.')
    elif entity_id is not None:
        raise ProductError('id is not accepted for create or list.')
    if action in ('update', 'delete'):
        if expected_version is None or not reason.strip():
            raise ProductError('expected_version and a non-empty reason are required for update or delete.')
    elif expected_version is not None or reason:
        raise ProductError('expected_version and reason apply only to update or delete.')
    if action in ('create', 'update'):
        if not changes:
            raise ProductError('changes is required for create or update.')
    elif changes:
        raise ProductError('changes applies only to create or update.')


def check_archive(task: Task, requirement: Requirement, expected_version: int, summary: str):
    if requirement.task_id != task.id or requirement.project_id != task.project_id:
        raise ProductError('Requirement is outside the selected Task.', 'not_found')
    if not summary.strip():
        raise ProductError('A completion summary is required.')
    if requirement.status == RequirementStatus.DELETED:
        raise Conflict('Deleted Requirements cannot be archived.')
    if requirement.status == RequirementStatus.ARCHIVED:
        if requirement.version == expected_version + 1 and requirement.summary == summary:
            return False  # Idempotent retry; no second Task completion.
        raise Conflict('Requirement was already archived with different input.')
    if requirement.version != expected_version:
        raise Conflict('Requirement version is stale.')
    if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
        raise Conflict('Only active/testing Tasks accept Requirement archival; paused/released must transition first.')
    return True
