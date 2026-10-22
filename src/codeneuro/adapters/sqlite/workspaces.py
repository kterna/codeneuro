"""Project, task snapshots and explicit request receipts."""
from dataclasses import asdict
import json
import sqlalchemy as sa
from ...modules.tasks import Conflict, ProductError
from . import schema as s
from .common import Repo, _task, _worktree, _json


class WorkspacesRepo(Repo):
    def project_revision(self, project_id):
        row = self._one(sa.select(s.projects.c.rule_revision).where(s.projects.c.id == project_id))
        if row is None:
            raise ProductError('Project not found.', 'not_found')
        return row['rule_revision']

    def create_project(self, project_id, name):
        self.c.execute(s.projects.insert().values(id=project_id, name=name))

    def delete_project(self, project_id):
        self.c.execute(s.rules.update().where(s.rules.c.project_id == project_id).values(origin_rule_id=None))
        rules = sa.select(s.rules.c.id).where(s.rules.c.project_id == project_id)
        requirements = sa.select(s.requirements.c.id).where(s.requirements.c.project_id == project_id)
        tasks = sa.select(s.tasks.c.id).where(s.tasks.c.project_id == project_id)
        deliveries = sa.select(s.deliveries.c.id).where(s.deliveries.c.project_id == project_id)
        indirect = {
            'rule_validation_state': s.rule_validation_state.c.rule_id.in_(rules),
            'rule_observations': s.rule_observations.c.rule_id.in_(rules),
            'requirement_versions': s.requirement_versions.c.requirement_id.in_(requirements),
            'task_versions': s.task_versions.c.task_id.in_(tasks),
            'rule_versions': s.rule_versions.c.rule_id.in_(rules),
            'projects': s.projects.c.id == project_id,
        }
        for name in ('delivery_rules', 'delivery_requirements', 'delivery_tasks', 'delivery_findings',
                     'delivery_selections', 'feedback'):
            indirect[name] = s.metadata.tables[name].c.delivery_id.in_(deliveries)
        for table in reversed(s.metadata.sorted_tables):
            predicate = table.c.project_id == project_id if 'project_id' in table.c else indirect[table.name]
            self.c.execute(table.delete().where(predicate))

    def list_projects(self):
        return [dict(row) for row in self.c.execute(sa.select(s.projects).order_by(s.projects.c.id)).mappings()]

    def counts(self, project_id):
        result = {}
        for name, table in (('requirements', s.requirements), ('tasks', s.tasks)):
            working = ('active', 'accepting') if name == 'requirements' else ('active', 'testing')
            row = self._one(sa.select(sa.func.count().label('total'),
                sa.func.sum(sa.case((sa.and_(table.c.status.in_(working), table.c.archived_at.is_(None)), 1), else_=0)).label('working'),
                sa.func.sum(sa.case((table.c.status == 'completed', 1), else_=0)).label('completed'),
                sa.func.sum(sa.case((table.c.archived_at.is_not(None), 1), else_=0)).label('archived')).where(
                    table.c.project_id == project_id, table.c.deleted_at.is_(None)))
            result[name] = {key: value or 0 for key, value in row.items()}
        return result

    def get_task(self, task_id, project_id=None):
        query = sa.select(s.tasks).where(s.tasks.c.id == task_id)
        if project_id is not None:
            query = query.where(s.tasks.c.project_id == project_id)
        return _task(self._one(query))

    def list_tasks(self, project_id, *, requirement_id=None, statuses=None, cursor=None, limit=None):
        query = sa.select(s.tasks).where(s.tasks.c.project_id == project_id, s.tasks.c.deleted_at.is_(None))
        if requirement_id is not None:
            query = query.where(s.tasks.c.requirement_id == requirement_id)
        if statuses is not None:
            query = query.where(s.tasks.c.status.in_(statuses))
        if cursor is not None:
            query = query.where(s.tasks.c.id > cursor)
        query = query.order_by(s.tasks.c.id)
        if limit is not None:
            query = query.limit(limit)
        return [_task(row) for row in self.c.execute(query).mappings()]

    def _values(self, task):
        values = asdict(task)
        values['verification_report_ids_json'] = _json(values.pop('verification_report_ids'))
        return values

    def _snapshot(self, task):
        self.c.execute(s.task_versions.insert().values(task_id=task.id, version=task.version,
                                                       snapshot_json=_json(asdict(task))))

    def create_task(self, task):
        self.c.execute(s.tasks.insert().values(**self._values(task)))
        self._snapshot(task)

    def update_task(self, task, expected_version):
        changed = self.c.execute(s.tasks.update().where(s.tasks.c.id == task.id,
            s.tasks.c.version == expected_version).values(**self._values(task),
                context_revision=s.tasks.c.context_revision + 1))
        if changed.rowcount != 1:
            raise Conflict('Task version is stale.')
        self._snapshot(task)

    def task_context_revision(self, task_id):
        return self.c.execute(sa.select(s.tasks.c.context_revision).where(s.tasks.c.id == task_id)).scalar_one()

    def task_versions(self, task_id, cursor=None, limit=20):
        query = sa.select(s.task_versions).where(s.task_versions.c.task_id == task_id)
        if cursor is not None:
            query = query.where(s.task_versions.c.version > cursor)
        return [json.loads(row.snapshot_json) for row in self.c.execute(
            query.order_by(s.task_versions.c.version).limit(limit))]

    def request(self, project_id, operation, request_id):
        if request_id is None:
            return None
        row = self._one(sa.select(s.request_receipts).where(s.request_receipts.c.project_id == project_id,
            s.request_receipts.c.operation == operation, s.request_receipts.c.request_id == request_id))
        return (row['fingerprint'], json.loads(row['response_json'])) if row else None

    def record_request(self, project_id, operation, request_id, fingerprint, result):
        if request_id is not None:
            self.c.execute(s.request_receipts.insert().values(project_id=project_id, operation=operation,
                request_id=request_id, fingerprint=fingerprint, resource_id=result['id'], response_json=_json(result)))

    def register_worktree(self, worktree):
        existing = self._one(sa.select(s.worktrees).where(s.worktrees.c.id == worktree.id))
        if existing:
            if existing['repo_identity'] and worktree.repo_identity and existing['repo_identity'] != worktree.repo_identity:
                raise Conflict('Worktree repository identity cannot be rebound.')
            self.c.execute(s.worktrees.update().where(s.worktrees.c.id == worktree.id).values(
                git_branch=worktree.git_branch, repo_identity=worktree.repo_identity or existing['repo_identity']))
        else:
            self.c.execute(s.worktrees.insert().values(**asdict(worktree)))

    def project_worktrees(self, project_id):
        return [_worktree(row) for row in self.c.execute(sa.select(s.worktrees).where(
            s.worktrees.c.project_id == project_id).order_by(s.worktrees.c.id)).mappings()]
