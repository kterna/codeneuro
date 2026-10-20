"""Read-only projections; never scan client-declared workspace paths."""
from dataclasses import asdict
import json

from ..modules.ledger import density
from ..modules.context import ContextQuery
from ..modules.knowledge import matches, relative_path
from ..modules.tasks import ProductError
from ..modules.workspaces import Actor
from .workspaces import Workspaces
from .common import page_cursor


class Ledger(Workspaces):
    @staticmethod
    def _events(tx, project_id, limit=100, before=None):
        if not 1 <= limit <= 100 or (before is not None and before < 1):
            raise ProductError('Use a page size of 1–100 and a positive event cursor.')
        rows = tx.audit.project_audit(project_id, limit + 1, before)
        items = rows[:limit]
        for event in items:
            event['details'] = json.loads(event.pop('details_json'))
        return {'items': items, 'next_cursor': items[-1]['sequence'] if len(rows) > limit else None}

    def events(self, actor: Actor, project_id: str, limit=100, before=None):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            return self._events(tx, project_id, limit, before)

    def project(self, actor: Actor, project_id: str):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            rules = tx.knowledge.project_rules(project_id)
            scores = tx.feedback.current_rule_scores(project_id)
            for rule in rules:
                rule.update(scores[rule['id']])

            proposals = []
            for proposal in tx.knowledge.list_proposals(project_id):
                target = tx.knowledge.get_rule(proposal.target_rule_id)
                proposals.append({**asdict(proposal),
                    'target_snapshot': tx.knowledge.rule_snapshot(proposal.target_rule_id, proposal.target_version),
                    'current_target_version': target.version if target else None})
            events = self._events(tx, project_id)
            tasks = tx.workspaces.list_tasks(project_id, limit=101)
            requirements = tx.requirements.project_requirements(project_id, limit=21)
            progress = tx.requirements.progress([item.id for item in requirements[:20]])
            return {'project_id': project_id,
                    'counts': tx.workspaces.counts(project_id),
                    'taxonomy': tx.topics.state(project_id),
                    'topic_coverage': tx.topics.coverage(project_id),
                    'topics': [asdict(item) for item in tx.topics.list(project_id, limit=100)],
                    'tasks': [{**{key: getattr(task, key) for key in ('id', 'project_id', 'requirement_id',
                        'status', 'version', 'archived_at')}, 'title': task.title[:200],
                        'description': task.description[:200], 'truncated': len(task.title) > 200 or len(task.description) > 200}
                        for task in tasks[:100]],
                    'tasks_next_cursor': page_cursor(tasks[99].id, 'tasks', project_id) if len(tasks) > 100 else None,
                    'worktrees': [asdict(worktree) for worktree in tx.workspaces.project_worktrees(project_id)],
                    'requirements': [{**{key: getattr(item, key) for key in ('id', 'project_id', 'status', 'version', 'archived_at')},
                        'title': item.title[:200], 'text': item.text[:200],
                        'truncated': len(item.title) > 200 or len(item.text) > 200,
                        'progress': progress.get(item.id, {'total': 0, 'completed': 0})} for item in requirements[:20]],
                    'requirements_next_cursor': page_cursor(requirements[19].id, 'requirements', project_id) if len(requirements) > 20 else None,
                    'findings': [asdict(item) for item in tx.context.project_findings(project_id)],
                    'rules': rules,
                    'scope_density': density(rules),
                    'proposals': proposals,
                    'events': events['items'], 'events_next_cursor': events['next_cursor']}

    def scope_tree(self, actor: Actor, project_id: str, worktree_id: str | None = None):
        """Registered scope patterns, explicitly not an index of remote files."""
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            worktree = None
            if worktree_id:
                worktree = next((w for w in tx.workspaces.project_worktrees(project_id)
                                 if w.id == worktree_id), None)
                if worktree is None:
                    raise ProductError('Worktree is outside this project.', 'not_found')
            scopes = {}
            for rule in tx.knowledge.project_rules(project_id):
                if rule['status'] != 'active':
                    continue
                for pattern in rule['patterns']:
                    scopes.setdefault(pattern, set()).add(rule['id'])
            return {'source': 'registered_scopes', 'workspace': worktree.workspace if worktree else None,
                    'worktree_id': worktree_id,
                    'tree': [{'path': path, 'is_dir': False, 'rule_ids': sorted(ids)}
                             for path, ids in sorted(scopes.items())]}

    def inspect_path(self, actor: Actor, project_id: str, path: str, priorities: tuple,
                     task_id: str | None = None):
        """Reuse JIT's anchored matcher without a Delivery or filesystem access."""
        path = relative_path(path)
        query = ContextQuery(priorities=priorities, files=(path,))
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            effective_task = task_id
            if task_id:
                task, parent = self._task(tx, task_id, project_id)
                if (task.archived_at or parent.archived_at or task.status not in ('active', 'testing', 'completed')
                        or parent.status not in ('active', 'accepting')):
                    effective_task = None
            rules = [r for r in tx.knowledge.visible_rules(project_id, effective_task)
                     if r.priority in query.priorities and
                     (r.is_global or any(matches(pattern, path) for pattern in r.patterns))]
            return {'path': path, 'task_id': task_id, 'rule_ids': [r.id for r in rules],
                    'source': 'jit_scope_match', 'preview': True}
