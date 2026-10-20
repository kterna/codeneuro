"""Typed row conversion and a minimal common SQL cursor helper."""
import json
from sqlalchemy import Connection
from ...modules.knowledge import Priority, Rule
from ...modules.tasks import Requirement, RequirementStatus, Task, TaskStatus
from ...modules.workspaces import Worktree


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def task_snapshot(value):
    return Task(**{**value, 'status': TaskStatus(value['status']),
                   'verification_report_ids': tuple(value['verification_report_ids'])})


def requirement_snapshot(value):
    return Requirement(**{**value, 'status': RequirementStatus(value['status'])})


def _task(row):
    if row is None:
        return None
    value = dict(row)
    value.pop('context_revision')
    value['verification_report_ids'] = json.loads(value.pop('verification_report_ids_json'))
    return task_snapshot(value)


def _requirement(row):
    return requirement_snapshot(dict(row)) if row else None


def _rule(row, topics=()):
    return Rule(row['id'], row['project_id'], row['task_id'], row['title'],
                tuple(json.loads(row['points_json'])), tuple(json.loads(row['patterns_json'])),
                Priority(row['priority']), tuple(topics), row['version'], row['status'],
                row['origin_reason'], bool(row['is_global']), row['priority_reason'],
                json.loads(row['validation_spec_json']) if row['validation_spec_json'] else None) if row else None


def _worktree(row):
    return Worktree(**dict(row)) if row else None


class Repo:
    def __init__(self, connection: Connection):
        self.c = connection

    def _one(self, statement):
        row = self.c.execute(statement).mappings().first()
        return dict(row) if row else None
