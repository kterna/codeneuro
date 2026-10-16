"""Typed row conversion and a minimal common SQL cursor helper."""
from __future__ import annotations
import json
from sqlalchemy import Connection
from ...modules.knowledge import Priority, Rule
from ...modules.tasks import Requirement, RequirementStatus, Task, TaskStatus
from ...modules.workspaces import Session, Worktree

def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _task(row):
    return Task(row['id'], row['project_id'], row['title'], row['description'],
                TaskStatus(row['status']), row['revision'],
                TaskStatus(row['paused_from']) if row['paused_from'] else None) if row else None

def _requirement(row):
    return Requirement(row['id'], row['project_id'], row['task_id'], row['current_text'],
                       RequirementStatus(row['status']), row['version'], row['completion_summary']) if row else None

def _rule(row, topics=()):
    return Rule(row['id'], row['project_id'], row['task_id'], row['title'],
                tuple(json.loads(row['points_json'])), tuple(json.loads(row['patterns_json'])),
                Priority(row['priority']), tuple(topics), row['version'], row['status'],
                row['origin_reason'], bool(row['is_global']), row['priority_reason'],
                json.loads(row['validation_spec_json']) if row['validation_spec_json'] else None) if row else None

def _session(row):
    return Session(row['id'], row['project_id'], row['task_id'], row['workspace'],
                   row['worktree_id'], row['actor_id'], bool(row['debug']), row['state'],
                   row['knowledge_revision']) if row else None


def _worktree(row):
    return Worktree(row['id'], row['project_id'], row['actor_id'], row['workspace'],
                    row['machine_name'], row['platform'], row['repo_identity'], row['git_branch']) if row else None


class Repo:
    def __init__(self, connection: Connection):
        self.c = connection

    def _one(self, statement):
        row = self.c.execute(statement).mappings().first()
        return dict(row) if row else None
