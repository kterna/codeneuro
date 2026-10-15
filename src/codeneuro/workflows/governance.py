"""Versioned validation independent of retrieval paths; Hub never executes tests."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json

from ..modules.governance import (TestReport, assess, covered_checks, require_activation,
                                  validate_cases, validate_plan, validate_test_report)
from ..modules.knowledge import RANK, Priority, Rule, relative_path, validate_rule
from ..modules.tasks import Conflict, ProductError, RequirementStatus, TaskStatus
from ..modules.workspaces import Actor
from .common import _id
from .topics import require_topics
from .workspaces import Workspaces


def require_test_activation(tx, rule):
    state = tx.governance.state(rule.id)
    if not state or not rule.validation_spec or rule.validation_spec['kind'] != 'test':
        raise Conflict('This candidate has no version-bound test evidence.')
    require_activation(assess(rule.version, state['evidence_version'], state['half_life_days'],
                              tx.governance.observations(rule.id, state['evidence_version'])))
    for check in rule.validation_spec['checks']:
        require_activation(assess(rule.version, state['evidence_version'], state['half_life_days'],
            tx.governance.check_observations(rule.id, state['evidence_version'], check['id'])))


class Governance(Workspaces):
    @staticmethod
    def _task_rule(tx, session, rule_id, expected_version):
        rule = tx.knowledge.get_rule(rule_id)
        if not rule or rule.project_id != session.project_id or rule.task_id != session.task_id:
            raise ProductError('Rule is outside this session Task.', 'not_found')
        if rule.version != expected_version:
            raise Conflict('Rule version changed.')
        linked = tx.requirements.linked_requirement(rule_id)
        if linked and linked.status != RequirementStatus.ACTIVE:
            raise Conflict('The linked Requirement is archived; this Rule cannot be activated or changed.')
        state = tx.governance.state(rule_id)
        if not state or state['session_id'] != session.id:
            raise ProductError('Only its originating Agent session may mutate this draft.', 'forbidden')
        return rule, state

    @staticmethod
    def _stats(tx, rule, state):
        records = tx.governance.observations(rule.id, state['evidence_version'])
        return assess(rule.version, state['evidence_version'], state['half_life_days'], records)

    def create_task_rule(self, actor: Actor, session_id: str, title: str,
                         points: tuple[str, ...], patterns: tuple[str, ...], reason: str,
                         priority: Priority = Priority.P1, requirement_id: str | None = None,
                         half_life_days: int = 30, *, topics: tuple[str, ...], validation_spec: dict,
                         is_global: bool = False, priority_reason: str = ''):
        if not reason.strip() or not 1 <= half_life_days <= 3650:
            raise ProductError('Supply a reason and bounded evidence half-life.')
        validate_plan(validation_spec, len(points))
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            task = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
            if not task or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Select an active/testing Task before creating a Rule.')
            if requirement_id:
                requirement = tx.requirements.get_requirement(requirement_id, task.id)
                if not requirement or requirement.status != RequirementStatus.ACTIVE:
                    raise ProductError('Linked Requirement must be active in this Task.')
            rule = Rule(_id('rule'), session.project_id, task.id, title, points, patterns,
                        priority, tuple(sorted(topics)), 1, 'draft', is_global=is_global,
                        priority_reason=priority_reason, validation_spec=validation_spec)
            validate_rule(rule)
            require_topics(tx, rule.project_id, topics)
            tx.knowledge.create_rule(rule)
            tx.governance.create_state(rule.id, session_id, 1, half_life_days)
            if requirement_id:
                tx.requirements.link_rule(requirement_id, rule.id)
            tx.audit.record(rule.project_id, actor.id, 'rule.observed', rule.id,
                            {'requirement_id': requirement_id, 'reason': reason})
            return {'rule': asdict(rule), 'governance': asdict(self._stats(tx, rule, tx.governance.state(rule.id)))}

    def report_test(self, actor: Actor, session_id: str, request_id: str,
                    command: tuple[str, ...], paths: tuple[str, ...], exit_code: int,
                    started_at: str, finished_at: str, test_cases: tuple[dict, ...]):
        if not request_id or len(request_id) > 128:
            raise ProductError('A bounded test request ID is required.')
        for path in paths:
            relative_path(path)
        validate_test_report(command, paths, started_at, finished_at, exit_code)
        validate_cases(test_cases)
        cases = tuple(sorted(test_cases, key=lambda case: case['test_id']))
        payload = json.dumps([command, sorted(paths), exit_code, started_at, finished_at, cases],
                             sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            task = tx.workspaces.get_task(session.task_id, session.project_id) if session.task_id else None
            if not task or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Test evidence requires an active/testing Task.')
            previous = tx.governance.test_by_request(session_id, request_id)
            if previous:
                if previous[0] != fingerprint:
                    raise Conflict('Test request ID reused for different evidence.')
                return previous[1]
            if tx.governance.test_by_fingerprint(session_id, fingerprint):
                raise Conflict('The same reported test event is already recorded under another request ID.')
            report = TestReport(_id('test'), session.id, session.project_id, task.id,
                                tuple(sorted(paths)), command, exit_code, started_at, finished_at,
                                recorded_at=datetime.now(timezone.utc).isoformat(), test_cases=cases)
            tx.governance.record_test(report, request_id, fingerprint)
            tx.audit.record(session.project_id, actor.id, 'test.client_reported', report.id,
                            {'exit_code': exit_code, 'source': report.source})
            return report

    def observe_rule(self, actor: Actor, session_id: str, rule_id: str,
                     expected_version: int, test_report_id: str, supports: bool, reason: str,
                     check_ids: tuple[str, ...]):
        if not reason.strip() or type(supports) is not bool:
            raise ProductError('Observation needs an explicit verdict and reason.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            rule, state = self._task_rule(tx, session, rule_id, expected_version)
            task = tx.workspaces.get_task(rule.task_id, rule.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING) or rule.status in ('revoked', 'deprecated'):
                raise Conflict('Inactive Tasks or Rules cannot receive observations.')
            report = tx.governance.test_report(test_report_id)
            if not report or (report.project_id, report.task_id, report.session_id) != (
                    rule.project_id, rule.task_id, session_id):
                raise ProductError('Test evidence is outside this Rule and Agent session.')
            if datetime.fromisoformat(report.recorded_at) < datetime.fromisoformat(state['revision_at']):
                raise Conflict('This Rule requires evidence observed after its content revision.')
            covered_checks(rule.validation_spec or {}, report, check_ids, supports)
            selected = tuple(sorted(check_ids))
            prior = tx.governance.observation(rule.id, state['evidence_version'], report.id)
            if prior:
                if prior != (supports, reason, selected):
                    raise Conflict('This report already has a different observation.')
                return asdict(self._stats(tx, rule, state))
            tx.governance.record_observation(rule.id, state['evidence_version'], report.id, supports, reason, selected)
            tx.audit.record(rule.project_id, actor.id, 'rule.evidence_attached', rule.id,
                            {'test_report_id': report.id, 'supports': supports, 'check_ids': selected})
            return asdict(self._stats(tx, rule, state))

    def mutate_task_rule(self, actor: Actor, session_id: str, rule_id: str,
                         expected_version: int, action: str, reason: str,
                         title=None, points=None, patterns=None, priority=None,
                         topics=None, is_global=None, priority_reason=None, validation_spec=None):
        if not reason.strip():
            raise ProductError('Mutation reason is required.')
        updates = {key: value for key, value in dict(title=title, points=points, patterns=patterns,
            priority=priority, topics=topics, is_global=is_global, priority_reason=priority_reason,
            validation_spec=validation_spec).items() if value is not None}
        if topics is not None:
            updates['topics'] = tuple(sorted(topics))
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            rule, state = self._task_rule(tx, session, rule_id, expected_version)
            task = tx.workspaces.get_task(rule.task_id, rule.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING) or rule.status in ('deprecated', 'revoked'):
                raise Conflict('Task or Rule is not active/testing/editable.')
            if action in ('activate', 'revoke') and updates:
                raise ProductError('Activation/revocation must not silently include edits.')
            semantic_change = False
            if action == 'activate':
                if rule.status != 'draft':
                    raise Conflict('Only a draft can be activated.')
                require_test_activation(tx, rule)
                changed = replace(rule, status='active', version=rule.version + 1)
            elif action == 'revoke':
                changed = replace(rule, status='revoked', version=rule.version + 1)
            elif action in ('update', 'reduce_priority'):
                if action == 'reduce_priority' and (set(updates) != {'priority'} or RANK[priority] <= RANK[rule.priority]):
                    raise ProductError('Reduce priority must only make priority less restrictive.')
                changed = replace(rule, **updates)
                validate_rule(changed)
                validate_plan(changed.validation_spec, len(changed.points))
                require_topics(tx, rule.project_id, changed.topics)
                semantic_change = any(getattr(changed, key) != getattr(rule, key) for key in
                    ('title', 'points', 'patterns', 'topics', 'is_global', 'validation_spec')) or RANK[changed.priority] < RANK[rule.priority]
                changed = replace(changed, version=rule.version + 1,
                                  status='draft' if semantic_change else rule.status)
            else:
                raise ProductError('Unsupported Agent Rule action.')
            tx.knowledge.update_rule(changed)
            if semantic_change:
                tx.governance.reset_state(rule.id, changed.version)
            tx.audit.record(rule.project_id, actor.id, 'rule.' + action, rule.id,
                            {'from_version': rule.version, 'version': changed.version, 'reason': reason})
            return {'rule': asdict(changed), 'governance': asdict(self._stats(tx, changed, tx.governance.state(rule.id)))}

    def review_task_rule(self, actor: Actor, project_id: str, rule_id: str,
                         expected_version: int, approve: bool, reason: str):
        if actor.role != 'human' or type(approve) is not bool or not reason.strip():
            raise ProductError('Explicit human review is required.', 'forbidden')
        with self.uow.write() as tx:
            rule = tx.knowledge.get_rule(rule_id)
            if not rule or rule.project_id != project_id or not rule.task_id:
                raise ProductError('Task Rule not found.', 'not_found')
            task = tx.workspaces.get_task(rule.task_id, project_id)
            linked = tx.requirements.linked_requirement(rule.id)
            if (rule.version != expected_version or rule.status != 'draft'
                    or task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING)
                    or (linked and linked.status != RequirementStatus.ACTIVE)):
                raise Conflict('Draft, Task or linked Requirement changed.')
            if approve:
                validate_rule(rule)
                validate_plan(rule.validation_spec, len(rule.points))
                if rule.validation_spec['kind'] != 'review':
                    raise Conflict('Testable rules require their declared tests; human review is not test evidence.')
                require_topics(tx, project_id, rule.topics)
            tx.governance.record_review(_id('review'), project_id, rule.id, rule.version, approve, reason, actor.id)
            if approve:
                tx.knowledge.update_rule(replace(rule, version=rule.version + 1, status='active'))
            tx.audit.record(project_id, actor.id, 'rule.reviewed', rule.id,
                            {'reviewed_version': rule.version, 'approve': approve, 'reason': reason})
            return tx.knowledge.get_rule(rule.id)
