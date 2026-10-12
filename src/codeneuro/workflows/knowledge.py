"""Knowledge application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

from dataclasses import replace
from ..modules.knowledge import (CATEGORIES, ContractProposal, Priority, Rule,
                                 check_promotable, relative_path)
from ..modules.tasks import Conflict, ProductError, TaskStatus
from ..modules.workspaces import Actor
from .common import _id
from .workspaces import Workspaces


class Knowledge(Workspaces):
    def create_rule(self, actor: Actor, project_id: str, title: str,
                    points: tuple[str, ...], patterns: tuple[str, ...],
                    priority: Priority = Priority.P1, category: str = 'business',
                    task_id: str | None = None):
        if actor.role != 'human':
            raise ProductError('Rule activation requires the reviewed entry point.', 'forbidden')
        if not title.strip() or not points or any(not point.strip() for point in points) or not patterns:
            raise ProductError('Rule needs a title, clauses and scope.')
        if category not in CATEGORIES:
            raise ProductError('Invalid category.')
        for pattern in patterns:
            relative_path(pattern, pattern=True)
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            if task_id:
                task = tx.workspaces.get_task(task_id, project_id)
                if task is None or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                    raise Conflict('Task Rule needs an active/testing Task.')
            rule = Rule(_id('rule'), project_id, task_id, title, points, patterns,
                        priority, category, 1, 'active')
            tx.knowledge.create_rule(rule)
            tx.audit.record(project_id, actor.id, 'rule.created', rule.id, {'task_id': task_id})
            return rule

    def propose_contract(self, actor: Actor, session_id: str, target_rule_id: str,
                         title: str, points: tuple[str, ...], patterns: tuple[str, ...],
                         priority: Priority, category: str, reason: str):
        if (not title.strip() or not points or not patterns or not reason.strip()
                or any(not point.strip() for point in points) or category not in CATEGORIES):
            raise ProductError('Proposed final contract needs complete clauses, scope and reason.')
        for pattern in patterns:
            relative_path(pattern, pattern=True)
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Contract proposal needs a Task-bound session.')
            task = tx.workspaces.get_task(session.task_id, session.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Only an active/testing Task can propose a contract update.')
            target = tx.knowledge.get_rule(target_rule_id)
            if target is None or target.project_id != session.project_id or target.task_id is not None or target.status != 'active':
                raise ProductError('Only an active project contract can be proposed for update.', 'not_found')
            proposal = ContractProposal(_id('proposal'), session.project_id, task.id,
                session.id, target.id, target.version, title, points, patterns,
                priority, category, reason)
            tx.knowledge.create_proposal(proposal)
            tx.audit.record(session.project_id, actor.id, 'contract.proposed', proposal.id,
                            {'target_rule_id': target.id, 'target_version': target.version})
            return proposal

    def review_contract(self, actor: Actor, project_id: str, proposal_id: str,
                        approve: bool, reason: str):
        if actor.role != 'human' or type(approve) is not bool or not reason.strip():
            raise ProductError('Explicit human approval/rejection and reason are required.', 'forbidden')
        with self.uow.write() as tx:
            proposal = tx.knowledge.get_proposal(proposal_id)
            if proposal is None or proposal.project_id != project_id:
                raise ProductError('Proposal not found in this project.', 'not_found')
            result = 'approved' if approve else 'rejected'
            if proposal.status != 'pending':
                if (proposal.status == result and proposal.reviewer_id == actor.id
                        and proposal.decision_reason == reason):
                    return proposal
                raise Conflict('Contract proposal already reviewed with different input.')
            target = tx.knowledge.get_rule(proposal.target_rule_id)
            if approve:
                if (target is None or target.project_id != project_id or target.task_id is not None
                        or target.status != 'active' or target.version != proposal.target_version):
                    raise Conflict('Target contract changed since the Agent proposal.')
                amended = replace(target, title=proposal.title, points=proposal.points,
                                  patterns=proposal.patterns, priority=proposal.priority,
                                  category=proposal.category, version=target.version + 1)
                tx.knowledge.update_rule(amended)
                tx.audit.record(project_id, actor.id, 'contract.updated', target.id,
                                {'proposal_id': proposal.id, 'previous_version': target.version,
                                 'version': amended.version})
            tx.knowledge.decide_proposal(proposal, result, reason, actor.id)
            tx.audit.record(project_id, actor.id, 'contract.reviewed', proposal.id,
                            {'decision': result, 'reason': reason})
            return tx.knowledge.get_proposal(proposal.id)

    def promote_rule(self, actor: Actor, session_id: str, rule_id: str,
                     expected_version: int, reason: str):
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Rule promotion requires a Task-bound session.')
            task = tx.workspaces.get_task(session.task_id, session.project_id)
            source = tx.knowledge.get_rule(rule_id)
            if source is None or source.project_id != session.project_id or source.task_id != session.task_id:
                raise ProductError('Rule outside this Task.', 'not_found')
            previous = tx.knowledge.promoted_rule(rule_id, expected_version)
            if previous:
                if previous.origin_reason != reason:
                    raise Conflict('Rule was already promoted with another reason.')
                return previous
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Cannot promote a Rule from an inactive Task.')
            check_promotable(source, session.task_id, expected_version, reason)
            promoted = replace(source, id=_id('rule'), task_id=None, version=1,
                               origin_reason=reason)
            tx.knowledge.create_rule(promoted, origin=(rule_id, expected_version))
            tx.knowledge.deprecate_rule(source)
            tx.audit.record(session.project_id, actor.id, 'rule.promoted', promoted.id,
                     {'source_id': rule_id, 'source_version': expected_version, 'reason': reason})
            return promoted
