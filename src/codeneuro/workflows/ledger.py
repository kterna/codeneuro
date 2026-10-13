"""Read-only projections; never scan client-declared workspace paths."""
from dataclasses import asdict
import json

from ..modules.ledger import density
from ..modules.knowledge import matches, relative_path
from ..modules.tasks import ProductError
from ..modules.workspaces import Actor
from .workspaces import Workspaces


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
                rule.pop('points_json')
                rule.pop('patterns_json')
            proposals = []
            for proposal in tx.knowledge.list_proposals(project_id):
                target = tx.knowledge.get_rule(proposal.target_rule_id)
                proposals.append({**asdict(proposal),
                    'target_snapshot': tx.knowledge.rule_snapshot(proposal.target_rule_id, proposal.target_version),
                    'current_target_version': target.version if target else None})
            events = self._events(tx, project_id)
            return {'project_id': project_id,
                    'tasks': [asdict(task) for task in tx.workspaces.list_tasks(project_id)],
                    'worktrees': [asdict(worktree) for worktree in tx.workspaces.project_worktrees(project_id)],
                    'requirements': [asdict(item) for item in tx.requirements.project_requirements(project_id)],
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

    def inspect_path(self, actor: Actor, project_id: str, path: str, task_id: str | None = None):
        """Reuse JIT's anchored matcher without a Delivery or filesystem access."""
        path = relative_path(path)
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            if task_id:
                task = tx.workspaces.get_task(task_id, project_id)
                if not task or task.status not in ('active', 'testing'):
                    raise ProductError('Select an active/testing Task in this project.')
            rules = [r for r in tx.knowledge.visible_rules(project_id, task_id)
                     if any(matches(pattern, path) for pattern in r.patterns)]
            return {'path': path, 'task_id': task_id, 'rule_ids': [r.id for r in rules],
                    'source': 'jit_scope_match', 'preview': True}
