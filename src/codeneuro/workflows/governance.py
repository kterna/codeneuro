"""Agent-owned Task knowledge with client-reported evidence and versioned mutations."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json

from ..modules.governance import (TestReport, assess, require_activation,
                                  validate_test_report)
from ..modules.knowledge import (CATEGORIES, RANK, Priority, Rule, matches, relative_path)
from ..modules.tasks import Conflict, ProductError, RequirementStatus, TaskStatus
from ..modules.workspaces import Actor
from .common import _id
from .workspaces import Workspaces


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
                         priority: Priority = Priority.P1, category: str = 'business',
                         requirement_id: str | None = None, half_life_days: int = 30):
        if (not reason.strip() or not title.strip() or not points or not patterns or
                any(not point.strip() for point in points) or category not in CATEGORIES or
                not 1 <= half_life_days <= 3650):
            raise ProductError('Supply a Task Rule, reason, bounded half-life, scope and clauses.')
        for pattern in patterns:
            relative_path(pattern, pattern=True)
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.task_id:
                raise ProductError('Select a Task before creating a Rule.')
            task = tx.workspaces.get_task(session.task_id, session.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Task no longer accepts new observations.')
            if requirement_id:
                requirement = tx.requirements.get_requirement(requirement_id, task.id)
                if not requirement or requirement.status != RequirementStatus.ACTIVE:
                    raise ProductError('Linked Requirement must be active in this Task.')
            rule = Rule(_id('rule'), session.project_id, task.id, title, points, patterns,
                        priority, category, 1, 'draft')
            tx.knowledge.create_rule(rule)
            tx.governance.create_state(rule.id, session_id, 1, half_life_days)
            if requirement_id:
                tx.requirements.link_rule(requirement_id, rule.id)
            tx.audit.record(session.project_id, actor.id, 'rule.observed', rule.id,
                            {'requirement_id': requirement_id, 'reason': reason})
            return {'rule': asdict(rule), 'governance': asdict(self._stats(tx, rule, tx.governance.state(rule.id)))}

    def report_test(self, actor: Actor, session_id: str, request_id: str,
                    command: tuple[str, ...], paths: tuple[str, ...], exit_code: int,
                    started_at: str, finished_at: str):
        if not request_id or len(request_id) > 128:
            raise ProductError('A bounded test request ID is required.')
        for path in paths:
            relative_path(path)
        validate_test_report(command, paths, started_at, finished_at, exit_code)
        payload = json.dumps([command, paths, exit_code, started_at, finished_at],
                             separators=(',', ':'), ensure_ascii=False)
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
                                paths, command, exit_code, started_at, finished_at,
                                recorded_at=datetime.now(timezone.utc).isoformat())
            tx.governance.record_test(report, request_id, fingerprint)
            tx.audit.record(session.project_id, actor.id, 'test.client_reported', report.id,
                            {'exit_code': exit_code, 'source': report.source})
            return report

    def observe_rule(self, actor: Actor, session_id: str, rule_id: str,
                     expected_version: int, test_report_id: str, supports: bool, reason: str):
        if not reason.strip() or type(supports) is not bool:
            raise ProductError('Observation needs an explicit verdict and reason.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            rule, state = self._task_rule(tx, session, rule_id, expected_version)
            if rule.status in ('revoked', 'deprecated'):
                raise Conflict('Inactive Rules cannot receive Agent observations.')
            report = tx.governance.test_report(test_report_id)
            if not report or (report.project_id, report.task_id, report.session_id) != (
                    rule.project_id, rule.task_id, session_id):
                raise ProductError('Test evidence is outside this Rule and Agent session.')
            if not any(matches(pattern, file) for pattern in rule.patterns for file in report.paths):
                raise ProductError('Test evidence must cover at least one path in the Rule scope.')
            if supports and report.exit_code != 0:
                raise ProductError('Failed tests cannot support a Rule.')
            if datetime.fromisoformat(report.recorded_at) < datetime.fromisoformat(state['revision_at']):
                raise Conflict('This Rule requires evidence observed after its content revision.')
            prior = tx.governance.observation(rule.id, state['evidence_version'], report.id)
            if prior:
                if prior != (supports, reason):
                    raise Conflict('This report already has a different observation.')
                return asdict(self._stats(tx, rule, state))
            tx.governance.record_observation(rule.id, state['evidence_version'], report.id,
                                              supports, reason)
            tx.audit.record(rule.project_id, actor.id, 'rule.evidence_attached', rule.id,
                            {'test_report_id': report.id, 'supports': supports})
            return asdict(self._stats(tx, rule, state))

    def mutate_task_rule(self, actor: Actor, session_id: str, rule_id: str,
                         expected_version: int, action: str, reason: str,
                         title: str | None = None, points: tuple[str, ...] | None = None,
                         patterns: tuple[str, ...] | None = None,
                         priority: Priority | None = None):
        if not reason.strip():
            raise ProductError('Mutation reason is required.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            rule, state = self._task_rule(tx, session, rule_id, expected_version)
            task = tx.workspaces.get_task(rule.task_id, rule.project_id)
            if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict('Task is not active/testing.')
            if rule.status in ('deprecated', 'revoked'):
                raise Conflict('Inactive Rules cannot be autonomously edited.')
            semantic_change = False
            if action == 'activate':
                if rule.status != 'draft':
                    raise Conflict('Only a validated draft can be activated.')
                require_activation(self._stats(tx, rule, state))
                changed = replace(rule, status='active', version=rule.version + 1)
            elif action == 'revoke':
                changed = replace(rule, status='revoked', version=rule.version + 1)
            elif action in ('update', 'reduce_priority'):
                chosen = priority or rule.priority
                if action == 'reduce_priority' and RANK[chosen] <= RANK[rule.priority]:
                    raise ProductError('Reduce priority must make the rule less restrictive.')
                if action == 'reduce_priority' and any(v is not None for v in (title, points, patterns)):
                    raise ProductError('Priority reduction must not change clauses or scope.')
                selected_title = title if title is not None else rule.title
                selected_points = points if points is not None else rule.points
                selected_patterns = patterns if patterns is not None else rule.patterns
                if not selected_title.strip() or not selected_points or not selected_patterns or any(
                        not point.strip() for point in selected_points):
                    raise ProductError('Rule content cannot be empty.')
                for pattern in selected_patterns:
                    relative_path(pattern, pattern=True)
                semantic_change = ((selected_title, selected_points, selected_patterns) !=
                                   (rule.title, rule.points, rule.patterns) or
                                   RANK[chosen] < RANK[rule.priority])
                changed = replace(rule, title=selected_title, points=selected_points,
                                  patterns=selected_patterns, priority=chosen,
                                  status='draft' if semantic_change else rule.status,
                                  version=rule.version + 1)
            else:
                raise ProductError('Unsupported Agent Rule action.')
            tx.knowledge.update_rule(changed)
            if action == 'update' and semantic_change:
                tx.governance.reset_state(rule.id, changed.version)
            tx.audit.record(rule.project_id, actor.id, 'rule.' + action, rule.id,
                            {'from_version': rule.version, 'version': changed.version, 'reason': reason})
            return {'rule': asdict(changed),
                    'governance': asdict(self._stats(tx, changed, tx.governance.state(rule.id)))}
