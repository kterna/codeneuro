"""Read-only human cognitive-asset projection; never becomes a second truth."""
from dataclasses import asdict
import json

from ..modules.ledger import density
from ..modules.workspaces import Actor
from .workspaces import Workspaces


class Ledger(Workspaces):
    def project(self, actor: Actor, project_id: str):
        with self.uow.read() as tx:
            tx.workspaces.project_revision(project_id)
            rules = tx.knowledge.project_rules(project_id)
            scores = tx.feedback.current_rule_scores(project_id)
            for rule in rules:
                rule.update(scores[rule['id']])
                rule.pop('points_json')
                rule.pop('patterns_json')
            events = tx.audit.project_audit(project_id)
            for event in events:
                event['details'] = json.loads(event.pop('details_json'))
            return {'project_id': project_id,
                    'tasks': [asdict(task) for task in tx.workspaces.list_tasks(project_id)],
                    'worktrees': [asdict(worktree) for worktree in tx.workspaces.project_worktrees(project_id)],
                    'requirements': [asdict(item) for item in tx.requirements.project_requirements(project_id)],
                    'findings': [asdict(item) for item in tx.context.project_findings(project_id)],
                    'rules': rules,
                    'scope_density': density(rules),
                    'proposals': [asdict(item) for item in tx.knowledge.list_proposals(project_id)],
                    'events': events}
