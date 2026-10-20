"""Business requirements and independently verified tasks; no execution sessions."""
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
    COMPLETED = 'completed'
    PAUSED = 'paused'


class RequirementStatus(StrEnum):
    DRAFT = 'draft'
    ACTIVE = 'active'
    ACCEPTING = 'accepting'
    COMPLETED = 'completed'


@dataclass(frozen=True)
class Task:
    id: str
    project_id: str
    requirement_id: str
    title: str
    description: str
    status: TaskStatus
    version: int = 1
    acceptance_criteria: str = ''
    paused_from: TaskStatus | None = None
    verification_summary: str | None = None
    verification_report_ids: tuple[str, ...] = ()
    archived_at: str | None = None
    deleted_at: str | None = None


@dataclass(frozen=True)
class Requirement:
    id: str
    project_id: str
    title: str
    text: str
    status: RequirementStatus
    version: int = 1
    original_text: str = ''
    acceptance_criteria: str = ''
    completion_summary: str | None = None
    archived_at: str | None = None
    deleted_at: str | None = None


def validate_crud(action, entity_id, expected_version, changes, reason):
    if action not in ('create', 'list', 'get', 'update', 'delete'):
        raise ProductError('Use create, list, get, update or delete.')
    if action in ('get', 'update', 'delete'):
        if not entity_id:
            raise ProductError('id is required for get, update and delete.')
    elif entity_id is not None:
        raise ProductError('id is not accepted for create or list.')
    if action in ('update', 'delete'):
        if type(expected_version) is not int or expected_version < 1 or not reason.strip():
            raise ProductError('A positive expected_version and non-empty reason are required.')
    elif expected_version is not None or reason:
        raise ProductError('expected_version and reason apply only to update or delete.')
    if action in ('create', 'update'):
        if not changes:
            raise ProductError('changes is required for create or update.')
    elif changes:
        raise ProductError('changes applies only to create or update.')


def validate_page(statuses, cursor, limit, states):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ProductError('List limit must be 1–100.')
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 256):
        raise ProductError('Use the next_cursor returned by this list (at most 256 characters).')
    if statuses is not None and (not statuses or len(set(statuses)) != len(statuses)
                                or any(state not in states for state in statuses)):
        raise ProductError('Use distinct supported statuses; omit for all states.')


def validate_text_changes(changes, fields):
    for name in fields:
        if name in changes and not isinstance(changes[name], str):
            raise ProductError(f'{name} must be a string.')
    if 'title' in changes and (not changes['title'].strip() or len(changes['title']) > 500):
        raise ProductError('title must contain 1–500 characters.')
    if 'archived' in changes and type(changes['archived']) is not bool:
        raise ProductError('archived must be an explicit boolean.')


def require_open(item):
    if item.deleted_at:
        raise Conflict('This record is deleted; its history remains readable.')
    if item.archived_at:
        raise Conflict('Restore this archived record before changing its business content.')


def require_working(task, requirement, *, allow_completed=False):
    require_open(task)
    require_open(requirement)
    allowed = {TaskStatus.ACTIVE, TaskStatus.TESTING}
    if allow_completed:
        allowed.add(TaskStatus.COMPLETED)
    if task.status not in allowed or requirement.status not in ('active', 'accepting'):
        raise Conflict('This operation needs an active/testing Task and an active/accepting Requirement.')


def ready_for_acceptance(tasks):
    current = [task for task in tasks if not task.deleted_at]
    return bool(current) and all(task.status == TaskStatus.COMPLETED for task in current)
