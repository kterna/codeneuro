"""Versioned knowledge and anchored path-scope policy."""
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase

from .tasks import Conflict, ProductError


class Priority(StrEnum):
    P0 = 'P0'
    P1 = 'P1'
    P2 = 'P2'


RANK = {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2}
CATEGORIES = frozenset({'business', 'security', 'gotcha'})


@dataclass(frozen=True)
class ContractProposal:
    id: str
    project_id: str
    task_id: str
    session_id: str
    target_rule_id: str
    target_version: int
    title: str
    points: tuple[str, ...]
    patterns: tuple[str, ...]
    priority: Priority
    category: str
    reason: str
    status: str = 'pending'
    decision_reason: str | None = None
    reviewer_id: str | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    project_id: str
    task_id: str | None
    title: str
    points: tuple[str, ...]
    patterns: tuple[str, ...]
    priority: Priority
    category: str
    version: int
    status: str
    origin_reason: str | None = None

    def matches(self, files: tuple[str, ...]) -> bool:
        return any(matches(pattern, file) for pattern in self.patterns for file in files)


def relative_path(value: str, *, pattern: bool = False) -> str:
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value or '\x00' in value:
        raise ProductError('Expected a workspace-relative POSIX path.')
    parts = value.split('/')
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
