"""Versioned knowledge with controlled topics and optional anchored retrieval paths."""
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase

from .tasks import Conflict, ProductError
from .topics import validate_keys


class Priority(StrEnum):
    P0 = 'P0'
    P1 = 'P1'
    P2 = 'P2'
    P3 = 'P3'


RANK = {priority: rank for rank, priority in enumerate(Priority)}


@dataclass(frozen=True)
class ContractProposal:
    id: str
    project_id: str
    task_id: str
    target_rule_id: str
    target_version: int
    title: str
    points: tuple[str, ...]
    patterns: tuple[str, ...]
    priority: Priority
    topics: tuple[str, ...]
    reason: str
    status: str = 'pending'
    decision_reason: str | None = None
    reviewer_id: str | None = None
    is_global: bool = False
    priority_reason: str = ''
    validation_spec: dict | None = None
    source_rule_id: str | None = None
    source_version: int | None = None
    delivery_mode: str = 'full'
    applies_when: str = ''


@dataclass(frozen=True)
class Rule:
    id: str
    project_id: str
    task_id: str | None
    title: str
    points: tuple[str, ...]
    patterns: tuple[str, ...]
    priority: Priority
    topics: tuple[str, ...]
    version: int
    status: str
    origin_reason: str | None = None
    is_global: bool = False
    priority_reason: str = ''
    validation_spec: dict | None = None
    delivery_mode: str = 'full'
    applies_when: str = ''

    def matches(self, files: tuple[str, ...]) -> bool:
        return any(matches(pattern, file) for pattern in self.patterns for file in files)


def validate_rule(rule: Rule):
    if not rule.title.strip() or not rule.points or any(not point.strip() for point in rule.points):
        raise ProductError('Rule needs a title and non-empty clauses.')
    if not isinstance(rule.priority, Priority) or type(rule.is_global) is not bool:
        raise ProductError('Invalid priority or global declaration.')
    validate_keys(rule.topics)
    if not rule.topics and not rule.is_global:
        raise ProductError('Non-global Rules require registered topics; empty scope is not global.')
    if rule.priority == Priority.P0 and not rule.priority_reason.strip():
        raise ProductError('P0 requires an explicit consequence and applicability rationale.')
    if rule.delivery_mode not in ('full', 'card'):
        raise ProductError('Delivery mode must be full or card.')
    if rule.delivery_mode == 'card':
        if not rule.applies_when.strip():
            raise ProductError('Card Rules require a one-line applicability statement.')
        if len(rule.applies_when.strip()) > 60:
            raise ProductError('Applicability statements must stay within 60 characters.')
        if rule.is_global:
            raise ProductError('Global Rules must stay full text; they cannot be card-only.')
    elif rule.applies_when.strip():
        raise ProductError('Full-text Rules cannot carry an applicability statement.')
    for pattern in rule.patterns:
        relative_path(pattern, pattern=True)


def relative_path(value: str, *, pattern: bool = False) -> str:
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or '\x00' in value:
        raise ProductError('Expected a workspace-relative POSIX path.')
    parts = value.split('/')
    if value.endswith('/'):
        raise ProductError('Use a directory pattern such as src/**.' if pattern
                           else 'Supply a real file such as src/app.py; directory paths are not files.')
    if any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ProductError('Path escapes or ambiguously names the workspace.')
    if pattern and any('**' in p and p != '**' for p in parts):
        raise ProductError('** must occupy an entire path segment.')
    if not pattern and any('*' in p or '?' in p or '[' in p for p in parts):
        raise ProductError('File paths cannot be patterns.')
    return value


def matches(pattern: str, target: str) -> bool:
    expression = relative_path(pattern, pattern=True).split('/')
    segments = relative_path(target).split('/')
    seen: dict[tuple[int, int], bool] = {}

    def at(i: int, j: int) -> bool:
        key = (i, j)
        if key not in seen:
            if i == len(expression):
                value = j == len(segments)
            elif expression[i] == '**':
                value = at(i + 1, j) or (j < len(segments) and at(i, j + 1))
            else:
                value = j < len(segments) and fnmatchcase(segments[j], expression[i]) and at(i + 1, j + 1)
            seen[key] = value
        return seen[key]

    return at(0, 0)


def check_promotable(rule: Rule, task_id: str, expected_version: int, reason: str):
    if rule.task_id != task_id:
        raise ProductError('Only this Task’s short-term Rule can be promoted.', 'not_found')
    if rule.status != 'active' or rule.version != expected_version:
        raise Conflict('Rule was changed or is no longer active.')
    if not reason.strip():
        raise ProductError('Promotion reason is required.')
