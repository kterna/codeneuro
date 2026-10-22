"""Reviewed knowledge, exact promotion and candidate-backed contract proposals."""
from dataclasses import replace

from ..modules.governance import validate_plan
from ..modules.knowledge import ContractProposal, Priority, Rule, check_promotable, validate_rule
from ..modules.tasks import Conflict, ProductError
from ..modules.workspaces import Actor
from .common import _id, replay
from .governance import require_test_activation
from .topics import require_topics
from .workspaces import Workspaces


class Knowledge(Workspaces):
    def create_rule(self, actor: Actor, project_id: str, title: str, points: tuple[str, ...],
                    patterns: tuple[str, ...], priority: Priority = Priority.P1,
                    task_id: str | None = None, *, topics: tuple[str, ...], validation_spec: dict,
                    is_global: bool = False, priority_reason: str = '',
                    delivery_mode: str = 'full', applies_when: str = ''):
        if actor.role != 'human':
            raise ProductError('Rule activation requires the reviewed entry point.', 'forbidden')
        validate_plan(validation_spec, len(points))
        if validation_spec['kind'] != 'review':
            raise ProductError('Test-backed rules must be validated as Task candidates first.')
        rule = Rule(_id('rule'), project_id, task_id, title, points, patterns, priority,
                    tuple(sorted(topics)), 1, 'active', is_global=is_global,
                    priority_reason=priority_reason, validation_spec=validation_spec,
                    delivery_mode=delivery_mode, applies_when=applies_when.strip())
        validate_rule(rule)
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            if task_id:
                self._task(tx, task_id, project_id, writable=True)
            require_topics(tx, project_id, topics)
            tx.knowledge.create_rule(rule)
            tx.governance.record_review(_id('review'), project_id, rule.id, rule.version,
                                        True, validation_spec['basis'], actor.id)
            tx.audit.record(project_id, actor.id, 'rule.created', rule.id, {'task_id': task_id})
            return rule

    def classify_legacy_rule(self, actor, project_id, rule_id, expected_version, topics,
                             reason, patterns=None, priority=None, is_global=False, priority_reason='',
                             delivery_mode=None, applies_when=None):
        """Human normative re-confirmation of imported rules, never invented test evidence."""
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Human confirmation of the legacy rule and its applicability is required.', 'forbidden')
        with self.uow.write() as tx:
            old = tx.knowledge.get_rule(rule_id)
            if not old or old.project_id != project_id:
                raise ProductError('Rule not found.', 'not_found')
            if old.version != expected_version or old.validation_spec is not None or old.status not in ('active', 'draft'):
                raise Conflict('Only an unchanged, unclassified legacy rule can use migration review.')
            changed = replace(old, topics=tuple(sorted(topics)), patterns=old.patterns if patterns is None else patterns,
                priority=old.priority if priority is None else priority, is_global=is_global,
                priority_reason=priority_reason, validation_spec={'kind': 'review', 'basis': reason},
                delivery_mode=old.delivery_mode if delivery_mode is None else delivery_mode,
                applies_when=old.applies_when if applies_when is None else applies_when.strip(),
                version=old.version + 1)
            validate_rule(changed)
            require_topics(tx, project_id, topics)
            tx.knowledge.update_rule(changed)
            if tx.governance.state(rule_id):
                tx.governance.reset_state(rule_id, changed.version)
            tx.governance.record_review(_id('review'), project_id, changed.id, changed.version,
                                        True, reason, actor.id)
            tx.audit.record(project_id, actor.id, 'rule.classified', rule_id,
                            {'from_version': old.version, 'version': changed.version, 'reason': reason,
                             'basis': 'human_normative_review_not_test_evidence'})
            return changed

    def set_rule_applicability(self, actor: Actor, project_id: str, rule_id: str, expected_version: int,
                               delivery_mode: str, applies_when: str, reason: str):
        """Human edit of how a project Rule is delivered; clauses and scope stay unchanged."""
        if actor.role != 'human' or not reason.strip():
            raise ProductError('Explicit human confirmation and reason are required.', 'forbidden')
        if type(expected_version) is not int or expected_version < 1:
            raise ProductError('A positive expected_version is required.')
        with self.uow.write() as tx:
            rule = tx.knowledge.get_rule(rule_id)
            if not rule or rule.project_id != project_id or rule.task_id is not None:
                raise ProductError('Project Rule not found in this project.', 'not_found')
            if rule.status != 'active' or rule.version != expected_version:
                raise Conflict('Rule changed since the edit; refresh before confirming.')
            when = applies_when.strip()
            if (rule.delivery_mode, rule.applies_when) == (delivery_mode, when):
                return rule
            changed = replace(rule, delivery_mode=delivery_mode, applies_when=when, version=rule.version + 1)
            validate_rule(changed)
            tx.knowledge.update_rule(changed)
            tx.audit.record(project_id, actor.id, 'rule.applicability_updated', rule_id,
                            {'from_version': rule.version, 'version': changed.version,
                             'delivery_mode': changed.delivery_mode, 'reason': reason})
            return changed

    def retire_project_rule(self, actor: Actor, project_id: str, rule_id: str,
                            expected_version: int, reason: str, *, confirmed: bool = False,
                            request_id: str | None = None):
        """Explicit reviewed retirement; scores and Task lifecycle never authorize it."""
        if actor.role != 'human' or confirmed is not True:
            raise ProductError('Explicit human confirmation of project Rule retirement is required.', 'forbidden')
        if type(expected_version) is not int or expected_version < 1 or not reason.strip():
            raise ProductError('A positive expected_version and retirement reason are required.')
        payload = {'rule_id': rule_id, 'expected_version': expected_version, 'reason': reason, 'confirmed': confirmed}
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            fingerprint, previous = replay(tx, project_id, 'rule.retire', request_id, payload)
            if previous is not None:
                return previous
            rule = tx.knowledge.get_rule(rule_id)
            if not rule or rule.project_id != project_id or rule.task_id is not None:
                raise ProductError('Project Rule not found in this project.', 'not_found')
            if rule.version != expected_version or rule.status != 'active':
                raise Conflict('Only an unchanged active project Rule can be retired; refresh before confirming.')
            retired = replace(rule, status='deprecated', version=rule.version + 1)
            tx.knowledge.update_rule(retired)
            result = {'id': retired.id, 'project_id': project_id, 'version': retired.version, 'status': retired.status}
            tx.audit.record(project_id, actor.id, 'rule.retired', rule_id,
                            {'from_version': rule.version, 'version': retired.version,
                             'reason': reason, 'confirmed': True})
            tx.workspaces.record_request(project_id, 'rule.retire', request_id, fingerprint, result)
            return result

    def propose_contract(self, actor: Actor, task_id: str, target_rule_id: str,
                         expected_target_version: int, candidate_rule_id: str,
                         expected_candidate_version: int, reason: str):
        if not reason.strip():
            raise ProductError('Proposal reason is required.')
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id, writable=True, allow_completed=True)
            target = tx.knowledge.get_rule(target_rule_id)
            if not target or target.project_id != task.project_id or target.task_id is not None or target.status != 'active':
                raise ProductError('Only an active project contract can be proposed for update.', 'not_found')
            if target.version != expected_target_version:
                raise Conflict('Target contract version changed.')
            source = tx.knowledge.get_rule(candidate_rule_id)
            if not source or source.project_id != task.project_id or source.task_id != task.id:
                raise ProductError('Candidate must belong to the selected Task.', 'not_found')
            if source.version != expected_candidate_version or source.status not in ('draft', 'active'):
                raise Conflict('Candidate version or state changed.')
            validate_rule(source)
            validate_plan(source.validation_spec, len(source.points))
            require_topics(tx, source.project_id, source.topics)
            if source.validation_spec['kind'] == 'test':
                if source.status != 'active':
                    raise Conflict('Validate and activate the test-backed candidate first.')
                require_test_activation(tx, source)
            proposal = ContractProposal(_id('proposal'), task.project_id, task.id,
                target.id, target.version, source.title, source.points, source.patterns, source.priority,
                source.topics, reason, is_global=source.is_global, priority_reason=source.priority_reason,
                validation_spec=source.validation_spec, source_rule_id=source.id, source_version=source.version,
                delivery_mode=source.delivery_mode, applies_when=source.applies_when)
            tx.knowledge.create_proposal(proposal)
            tx.audit.record(task.project_id, actor.id, 'contract.proposed', proposal.id,
                            {'target_rule_id': target.id, 'target_version': target.version,
                             'source_rule_id': source.id, 'source_version': source.version})
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
                if proposal.status == result and proposal.reviewer_id == actor.id and proposal.decision_reason == reason:
                    return proposal
                raise Conflict('Contract proposal already reviewed with different input.')
            if approve:
                if not proposal.source_rule_id or not proposal.validation_spec:
                    raise Conflict('A candidate and validation plan are required; resubmit this incomplete proposal.')
                target = tx.knowledge.get_rule(proposal.target_rule_id)
                source = tx.knowledge.get_rule(proposal.source_rule_id)
                task, _ = self._task(tx, proposal.task_id, project_id, writable=True, allow_completed=True)
                if (not target or target.project_id != project_id or target.task_id is not None
                        or target.status != 'active' or target.version != proposal.target_version
                        or not source or source.project_id != project_id or source.task_id != proposal.task_id
                        or source.version != proposal.source_version or source.status not in ('draft', 'active')):
                    raise Conflict('Target contract or candidate changed since the proposal.')
                validate_rule(source)
                validate_plan(source.validation_spec, len(source.points))
                require_topics(tx, project_id, source.topics)
                if source.validation_spec['kind'] == 'test':
                    require_test_activation(tx, source)
                else:
                    tx.governance.record_review(_id('review'), project_id, source.id, source.version,
                                                True, reason, actor.id)
                amended = replace(target, title=source.title, points=source.points, patterns=source.patterns,
                    topics=source.topics, priority=source.priority, priority_reason=source.priority_reason,
                    is_global=source.is_global, validation_spec=source.validation_spec,
                    delivery_mode=source.delivery_mode, applies_when=source.applies_when,
                    version=target.version + 1)
                tx.knowledge.update_rule(amended)
                tx.knowledge.deprecate_rule(source)
                tx.audit.record(project_id, actor.id, 'contract.updated', target.id,
                                {'proposal_id': proposal.id, 'previous_version': target.version,
                                 'version': amended.version, 'source_rule_id': source.id, 'source_version': source.version})
            tx.knowledge.decide_proposal(proposal, result, reason, actor.id)
            tx.audit.record(project_id, actor.id, 'contract.reviewed', proposal.id,
                            {'decision': result, 'reason': reason})
            return tx.knowledge.get_proposal(proposal.id)

    def promote_rule(self, actor: Actor, task_id: str, rule_id: str,
                     expected_version: int, reason: str):
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id)
            source = tx.knowledge.get_rule(rule_id)
            if source is None or source.project_id != task.project_id or source.task_id != task.id:
                raise ProductError('Rule outside this Task.', 'not_found')
            previous = tx.knowledge.promoted_rule(rule_id, expected_version)
            if previous:
                if previous.origin_reason != reason:
                    raise Conflict('Rule was already promoted with another reason.')
                return previous
            self._task(tx, task_id, writable=True, allow_completed=True)
            check_promotable(source, task.id, expected_version, reason)
            validate_rule(source)
            validate_plan(source.validation_spec, len(source.points))
            require_topics(tx, source.project_id, source.topics)
            if source.validation_spec['kind'] == 'test':
                require_test_activation(tx, source)
            promoted = replace(source, id=_id('rule'), task_id=None, version=1, origin_reason=reason)
            tx.knowledge.create_rule(promoted, origin=(rule_id, expected_version))
            tx.knowledge.deprecate_rule(source)
            tx.audit.record(task.project_id, actor.id, 'rule.promoted', promoted.id,
                            {'source_id': rule_id, 'source_version': expected_version, 'reason': reason})
            return promoted
