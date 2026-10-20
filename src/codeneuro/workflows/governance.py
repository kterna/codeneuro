"""Task-owned rule validation; Hub records evidence and never executes tests."""
from dataclasses import asdict, replace
from datetime import datetime

from ..modules.governance import (TestReport, assess, covered_checks, require_activation,
                                  validate_cases, validate_plan, validate_test_report, test_event_fingerprint)
from ..modules.knowledge import RANK, Priority, Rule, relative_path, validate_rule
from ..modules.tasks import Conflict, ProductError
from .common import _id, _now, replay
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
    def _task_rule(tx, task, rule_id, expected_version):
        rule = tx.knowledge.get_rule(rule_id)
        if not rule or (rule.project_id, rule.task_id) != (task.project_id, task.id):
            raise ProductError('Rule is outside the selected Task.', 'not_found')
        if rule.version != expected_version:
            raise Conflict('Rule version changed.')
        state = tx.governance.state(rule_id)
        if not state:
            raise Conflict('This Rule has no candidate validation state.')
        return rule, state

    @staticmethod
    def _stats(tx, rule, state):
        return assess(rule.version, state['evidence_version'], state['half_life_days'],
                      tx.governance.observations(rule.id, state['evidence_version']))

    def create_task_rule(self, actor, task_id, title, points, patterns, reason,
                         priority=Priority.P1, half_life_days=30, *, topics, validation_spec,
                         is_global=False, priority_reason=''):
        if not reason.strip() or type(half_life_days) is not int or not 1 <= half_life_days <= 3650:
            raise ProductError('Supply a reason and bounded evidence half-life.')
        validate_plan(validation_spec, len(points))
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id, writable=True)
            rule = Rule(_id('rule'), task.project_id, task.id, title, points, patterns,
                        priority, tuple(sorted(topics)), 1, 'draft', is_global=is_global,
                        priority_reason=priority_reason, validation_spec=validation_spec)
            validate_rule(rule)
            require_topics(tx, rule.project_id, topics)
            tx.knowledge.create_rule(rule)
            tx.governance.create_state(rule.id, 1, half_life_days)
            tx.audit.record(rule.project_id, actor.id, 'rule.observed', rule.id, {'reason': reason})
            return {'rule': asdict(rule), 'governance': asdict(self._stats(tx, rule, tx.governance.state(rule.id)))}

    def report_test(self, actor, task_id, request_id, command, paths, exit_code, started_at,
                    finished_at, test_cases, source=None):
        if not request_id:
            raise ProductError('A bounded test request ID is required.')
        for path in paths:
            relative_path(path)
        validate_test_report(command, paths, started_at, finished_at, exit_code)
        validate_cases(test_cases)
        cases = tuple(sorted(test_cases, key=lambda case: case['test_id']))
        payload = {'task_id': task_id, 'command': command, 'paths': sorted(paths), 'exit_code': exit_code,
                   'started_at': started_at, 'finished_at': finished_at, 'test_cases': cases}
        event = test_event_fingerprint(command, paths, exit_code, started_at, finished_at, cases)
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id)
            fingerprint, previous = replay(tx, task.project_id, 'test.report', request_id, payload)
            if previous:
                return tx.governance.test_report(previous['id'])
            self._task(tx, task_id, writable=True)
            prior = tx.governance.test_by_fingerprint(task.id, event)
            if prior:
                raise Conflict(f'This test event is already recorded as {prior.id}; reuse the original report.')
            report = TestReport(_id('test'), task.project_id, task.id, tuple(sorted(paths)), command,
                exit_code, started_at, finished_at, recorded_at=_now(), test_cases=cases)
            tx.governance.record_test(report, event)
            tx.workspaces.record_request(task.project_id, 'test.report', request_id, fingerprint, asdict(report))
            tx.audit.record(task.project_id, actor.id, 'test.client_reported', report.id,
                {'exit_code': exit_code, 'source': report.source, 'provenance': self._source(tx, actor, task.project_id, source)})
            return report

    def observe_rule(self, actor, task_id, rule_id, expected_version, test_report_id, supports, reason, check_ids):
        if not reason.strip() or type(supports) is not bool:
            raise ProductError('Observation needs an explicit verdict and reason.')
        with self.uow.write() as tx:
            task, _ = self._task(tx, task_id, writable=True)
            rule, state = self._task_rule(tx, task, rule_id, expected_version)
            if rule.status in ('revoked', 'deprecated'):
                raise Conflict('Inactive Rules cannot receive observations.')
            report = tx.governance.test_report(test_report_id)
            if not report or (report.project_id, report.task_id) != (task.project_id, task.id):
                raise ProductError('Test evidence is outside this Rule and Task.', 'not_found')
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
            tx.audit.record(task.project_id, actor.id, 'rule.evidence_attached', rule.id,
                            {'test_report_id': report.id, 'supports': supports, 'check_ids': selected})
            return asdict(self._stats(tx, rule, state))

    def mutate_task_rule(self, actor, task_id, rule_id, expected_version, action, reason,
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
            task, _ = self._task(tx, task_id, writable=True)
            rule, state = self._task_rule(tx, task, rule_id, expected_version)
            if rule.status in ('deprecated', 'revoked'):
                raise Conflict('Rule is not editable.')
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
                changed = replace(changed, version=rule.version + 1, status='draft' if semantic_change else rule.status)
            else:
                raise ProductError('Unsupported Agent Rule action.')
            tx.knowledge.update_rule(changed)
            if semantic_change:
                tx.governance.reset_state(rule.id, changed.version)
            tx.audit.record(rule.project_id, actor.id, 'rule.' + action, rule.id,
                {'from_version': rule.version, 'version': changed.version, 'reason': reason})
            return {'rule': asdict(changed), 'governance': asdict(self._stats(tx, changed, tx.governance.state(rule.id)))}

    def review_task_rule(self, actor, project_id, rule_id, expected_version, approve, reason):
        if actor.role != 'human' or type(approve) is not bool or not reason.strip():
            raise ProductError('Explicit human review is required.', 'forbidden')
        with self.uow.write() as tx:
            rule = tx.knowledge.get_rule(rule_id)
            if not rule or rule.project_id != project_id or not rule.task_id:
                raise ProductError('Task Rule not found.', 'not_found')
            self._task(tx, rule.task_id, project_id, writable=True, allow_completed=True)
            if rule.version != expected_version or rule.status != 'draft':
                raise Conflict('Draft version or status changed.')
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
