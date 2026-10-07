"""Task-scoped memory governance with recorded evidence and explicit human review.

No provider/network call is made inside a SQLite transaction. Test outcomes are
client-reported observations, not a claim that the Hub executed a command.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .database import Conflict, DomainError
from .models import Finding, Lifecycle, Priority, Rule, RuleStatus, TaskStatus
from .paths import relative_path
from .service import ContextService, now, uid


DDL = [
    "CREATE TABLE IF NOT EXISTS governance_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS governance_rule_state(
        rule_id TEXT PRIMARY KEY REFERENCES rules(id) ON DELETE CASCADE,
        session_id TEXT REFERENCES agent_sessions(id), evidence_version INTEGER NOT NULL,
        half_life_days REAL NOT NULL DEFAULT 30 CHECK(half_life_days>0),
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS governance_test_runs(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        task_id TEXT NOT NULL REFERENCES tasks(id), session_id TEXT NOT NULL REFERENCES agent_sessions(id),
        request_id TEXT NOT NULL, request_hash TEXT NOT NULL, command_json TEXT NOT NULL,
        command_hash TEXT NOT NULL, exit_code INTEGER NOT NULL, stdout TEXT NOT NULL, stderr TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT NOT NULL, paths_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'client_reported', created_at TEXT NOT NULL,
        UNIQUE(session_id,request_id))""",
    """CREATE TABLE IF NOT EXISTS governance_observations(
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES rules(id), rule_version INTEGER NOT NULL,
        test_run_id TEXT NOT NULL REFERENCES governance_test_runs(id), supports INTEGER NOT NULL,
        reason TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES agent_sessions(id), created_at TEXT NOT NULL,
        UNIQUE(rule_id,rule_version,test_run_id))""",
    """CREATE TABLE IF NOT EXISTS governance_reflections(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), task_id TEXT NOT NULL REFERENCES tasks(id),
        session_id TEXT NOT NULL REFERENCES agent_sessions(id), command_hash TEXT NOT NULL,
        status TEXT NOT NULL, failure_ids_json TEXT NOT NULL, recovery_run_id TEXT REFERENCES governance_test_runs(id),
        finding_id TEXT REFERENCES findings(id), analysis TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_governance_reflection ON governance_reflections(session_id,command_hash,status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_governance_test_evidence ON governance_test_runs(session_id,request_hash)",
    """CREATE TABLE IF NOT EXISTS governance_task_pauses(
        task_id TEXT PRIMARY KEY REFERENCES tasks(id), previous_status TEXT NOT NULL,
        paused_at TEXT NOT NULL, reason TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS governance_cleanups(
        session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id), request_id TEXT NOT NULL,
        result_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS governance_proposals(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), task_id TEXT REFERENCES tasks(id),
        change_json TEXT NOT NULL, source_refs_json TEXT NOT NULL, reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', result_json TEXT, created_at TEXT NOT NULL,
        reviewed_at TEXT, reviewer TEXT)""",
    """CREATE TABLE IF NOT EXISTS governance_preflights(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), session_id TEXT NOT NULL REFERENCES agent_sessions(id),
        request_id TEXT NOT NULL, input_hash TEXT NOT NULL, input_json TEXT NOT NULL, result_json TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(session_id,request_id))""",
    """CREATE TABLE IF NOT EXISTS governance_policies(
        rule_id TEXT NOT NULL REFERENCES rules(id), rule_version INTEGER NOT NULL, spec_json TEXT NOT NULL,
        reviewer TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(rule_id,rule_version))""",
    """CREATE TABLE IF NOT EXISTS governance_distill_requests(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), task_id TEXT NOT NULL REFERENCES tasks(id),
        source TEXT NOT NULL, source_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
        job_id TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
]


def ensure_schema(storage):
    with storage.transaction():
        for statement in DDL:
            storage.conn.execute(statement)
        version = storage.conn.execute("SELECT MAX(version) FROM governance_schema").fetchone()[0]
        if version and version > 1:
            raise DomainError('Governance schema is newer than this application.')
        storage.conn.execute('INSERT OR IGNORE INTO governance_schema VALUES(1,?)', (now(),))


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _required(text, name='reason', limit=30000):
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        raise DomainError(f'{name} must be nonempty and at most {limit} characters.')
    return text.strip()


def queue_distillation(storage, project_id, task_id, source, source_key):
    existing = storage.conn.execute('SELECT id FROM governance_distill_requests WHERE source_key=?', (source_key,)).fetchone()
    if existing:
        return existing['id']
    identifier = uid('distill')
    storage.conn.execute('''INSERT INTO governance_distill_requests
        (id,project_id,task_id,source,source_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?)''',
        (identifier, project_id, task_id, source, source_key, now(), now()))
    storage.audit(project_id, 'system', 'distillation.queued', identifier, {'task_id': task_id, 'source': source})
    return identifier


def task_transition(storage, task, status):
    """Called inside Storage's task transaction; only durable local writes here."""
    if task.status == status:
        return
    if status == TaskStatus.PAUSED:
        if task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
            raise Conflict('Only active or testing tasks can be paused.')
        storage.conn.execute('INSERT OR REPLACE INTO governance_task_pauses VALUES(?,?,?,?)',
                             (task.id, task.status.value, now(), 'Task paused'))
    elif task.status == TaskStatus.PAUSED and status in (TaskStatus.ACTIVE, TaskStatus.TESTING):
        saved = storage.conn.execute('SELECT previous_status FROM governance_task_pauses WHERE task_id=?', (task.id,)).fetchone()
        if saved and status.value != saved['previous_status']:
            raise Conflict('Resume the saved task state before moving it to another phase.')
        storage.conn.execute('DELETE FROM governance_task_pauses WHERE task_id=?', (task.id,))
    if status in (TaskStatus.RELEASED, TaskStatus.ARCHIVED):
        queue_distillation(storage, task.project_id, task.id, 'task_completion',
                           f'task:{task.id}:{task.updated_at.isoformat()}:{status.value}')


def rule_revision(storage, old, new_version, title, content_points, scope_patterns, priority):
    """Invalidate evidence when any transport changes the proposition it supported."""
    if (old.title, old.content_points, old.scope_patterns) != (title, content_points, scope_patterns) or priority.rank < old.priority.rank:
        storage.conn.execute('UPDATE governance_rule_state SET evidence_version=?,created_at=? WHERE rule_id=?',
                             (new_version, now(), old.id))


class GovernanceService:
    def __init__(self, storage, context_service=None, intelligence=None):
        self.storage = storage
        self.context = context_service or ContextService(storage)
        self.intelligence = intelligence

    def _session(self, session_id, *, active=True, task_required=True):
        session = self.context._session(session_id, active=active)
        if task_required and not session['task_id']:
            raise DomainError('Governance changes require a task-bound session.')
        self.storage.validate_scope(session['project_id'], session['task_id'], require_active=active)
        return session

    def _agent_rule(self, session, rule_id, expected_version):
        rule = self.storage.get_rule(rule_id)
        if not rule or rule.project_id != session['project_id'] or rule.task_id != session['task_id']:
            raise DomainError('Rule does not belong to the current task.', 'not_found', 404)
        if rule.lifecycle != Lifecycle.SHORT_TERM:
            raise DomainError('Long-term contracts require human review.', 'review_required', 403)
        if rule.version != expected_version:
            raise Conflict('Rule version changed; inspect the current version before editing.')
        return rule

    def _stats(self, rule, at=None):
        state = self.storage.conn.execute('SELECT * FROM governance_rule_state WHERE rule_id=?', (rule.id,)).fetchone()
        observations = [dict(row) for row in self.storage.conn.execute('''SELECT o.*,t.exit_code,t.source
            FROM governance_observations o JOIN governance_test_runs t ON t.id=o.test_run_id
            WHERE o.rule_id=? AND o.rule_version=? ORDER BY o.created_at''',
            (rule.id, state['evidence_version'] if state else rule.version))]
        positive = sum(bool(o['supports']) and o['exit_code'] == 0 for o in observations)
        negative = sum(not o['supports'] for o in observations)
        # A transparent Beta(1,1) evidence estimate, not an LLM truth probability.
        confidence = (1 + positive) / (2 + positive + negative)
        last = max((o['created_at'] for o in observations), default=None)
        age = max(0.0, ((_time(at) if at else datetime.utcnow()) - _time(last or rule.updated_at)).total_seconds() / 86400)
        half_life = state['half_life_days'] if state else 30
        effective = confidence * (0.5 ** (age / half_life))
        return {'rule_id': rule.id, 'version': rule.version, 'evidence_version': state['evidence_version'] if state else rule.version,
                'title': rule.title, 'priority': rule.priority.value, 'status': rule.status.value,
                'lifecycle': rule.lifecycle.value, 'task_id': rule.task_id,
                'stage': ('validated' if positive >= 2 and negative == 0 else 'observing') if state else 'human_managed',
                'confidence': round(confidence, 6), 'effective_confidence': round(effective, 6),
                'support_count': positive, 'contradiction_count': negative, 'last_observed_at': last,
                'half_life_days': half_life, 'age_days': round(age, 3), 'stale': bool(state and effective < 0.35),
                'observations': observations}

    def create_rule(self, *, session_id, title, content_points, scope_patterns, reason,
                    priority='P1', activate=False, evidence_ids=None, half_life_days=30):
        with self.storage.transaction():
            session = self._session(session_id)
            reason = _required(reason)
            if not 1 <= half_life_days <= 3650:
                raise DomainError('half_life_days must be between 1 and 3650.')
            self._validate_content(title, content_points, scope_patterns)
            rule = self.storage.create_rule(Rule(id=uid('rule'), project_id=session['project_id'],
                task_id=session['task_id'], title=title, content_points=content_points, scope_patterns=scope_patterns,
                priority=Priority(priority), lifecycle=Lifecycle.SHORT_TERM, status=RuleStatus.DRAFT,
                created_by=session_id))
            self.storage.conn.execute('INSERT INTO governance_rule_state VALUES(?,?,?,?,?)',
                                     (rule.id, session_id, rule.version, half_life_days, now()))
            for test_id in evidence_ids or []:
                self.observe_rule(session_id=session_id, rule_id=rule.id, expected_version=rule.version,
                                  test_run_id=test_id, supports=True, reason=reason)
            self.storage.audit(rule.project_id, session_id, 'governance.rule_created', rule.id, {'reason': reason, 'version': rule.version})
            if activate:
                return self.mutate_rule(session_id=session_id, rule_id=rule.id, expected_version=rule.version,
                                        action='activate', reason=reason)
            return {'rule': rule.model_dump(mode='json'), 'governance': self._stats(rule)}

    @staticmethod
    def _validate_content(title, points, scopes):
        _required(title, 'title', 500)
        if not points or len(points) > 100:
            raise DomainError('content_points requires 1 to 100 items.')
        for point in points:
            _required(point, 'content point', 10000)
        if not scopes or len(scopes) > 100:
            raise DomainError('scope_patterns requires 1 to 100 items.')
        for scope in scopes:
            relative_path(scope, pattern=True)

    def mutate_rule(self, *, session_id, rule_id, expected_version, action, reason,
                    title=None, content_points=None, scope_patterns=None, priority=None):
        with self.storage.transaction():
            session = self._session(session_id)
            rule = self._agent_rule(session, rule_id, expected_version)
            reason = _required(reason)
            if action == 'activate':
                stats = self._stats(rule)
                if stats['stage'] != 'validated' or stats['effective_confidence'] < 0.6:
                    raise Conflict('Activation needs two distinct successful evidence runs, no contradictions, and fresh confidence >= 0.6.')
                if rule.status in (RuleStatus.REVOKED, RuleStatus.DEPRECATED):
                    raise Conflict('Revoked or deprecated rules must be reviewed before reactivation.')
                self.storage.update_rule_status(rule_id, RuleStatus.ACTIVE, rule.version, session_id, reason)
            elif action == 'revoke':
                self.storage.update_rule_status(rule_id, RuleStatus.REVOKED, rule.version, session_id, reason)
            elif action in ('update', 'reduce_priority'):
                if rule.status in (RuleStatus.REVOKED, RuleStatus.DEPRECATED):
                    raise Conflict('Cannot autonomously edit a revoked or deprecated rule.')
                selected_priority = Priority(priority) if priority else rule.priority
                if action == 'reduce_priority' and selected_priority.rank <= rule.priority.rank:
                    raise DomainError('reduce_priority must select a less restrictive priority.')
                values = (title if title is not None else rule.title,
                          content_points if content_points is not None else rule.content_points,
                          scope_patterns if scope_patterns is not None else rule.scope_patterns)
                self._validate_content(*values)
                updated = self.storage.update_rule_content(rule_id, *values, selected_priority, reason, session_id, rule.version)
                changed_meaning = tuple(values) != (rule.title, rule.content_points, rule.scope_patterns)
                if changed_meaning or selected_priority.rank < rule.priority.rank:
                    # Existing observations support the old content, not the new claim.
                    self.storage.conn.execute('''INSERT INTO governance_rule_state VALUES(?,?,?,?,?)
                        ON CONFLICT(rule_id) DO UPDATE SET evidence_version=excluded.evidence_version''',
                        (rule_id, session_id, updated.version, 30, now()))
                    if updated.status == RuleStatus.ACTIVE:
                        self.storage.update_rule_status(rule_id, RuleStatus.DRAFT, updated.version, session_id,
                                                        'Changed content returns to observation: ' + reason)
                        self.storage.conn.execute('UPDATE governance_rule_state SET evidence_version=? WHERE rule_id=?',
                                                  (updated.version + 1, rule_id))
            else:
                raise DomainError('Unknown rule action.')
            result = self.storage.get_rule(rule_id)
            self.storage.audit(rule.project_id, session_id, 'governance.rule_' + action, rule_id,
                               {'reason': reason, 'previous_version': rule.version, 'version': result.version})
            return {'rule': result.model_dump(mode='json'), 'governance': self._stats(result)}

    def observe_rule(self, *, session_id, rule_id, expected_version, test_run_id, supports, reason):
        with self.storage.transaction():
            session = self._session(session_id)
            rule = self._agent_rule(session, rule_id, expected_version)
            evidence = self.storage.conn.execute('SELECT * FROM governance_test_runs WHERE id=?', (test_run_id,)).fetchone()
            if not evidence or evidence['project_id'] != rule.project_id or evidence['task_id'] != rule.task_id:
                raise DomainError('Test evidence must belong to this project and task.')
            if evidence['session_id'] != session_id:
                raise DomainError('A session can only attest evidence it submitted.')
            if not any(self.context.matcher.matches_pattern(pattern, path)
                       for path in json.loads(evidence['paths_json']) for pattern in rule.scope_patterns):
                raise DomainError('Test evidence must include a path within the rule scope.')
            if supports and evidence['exit_code'] != 0:
                raise DomainError('A failed test cannot support activation.')
            reason = _required(reason)
            state = self.storage.conn.execute('SELECT * FROM governance_rule_state WHERE rule_id=?', (rule_id,)).fetchone()
            if state and state['evidence_version'] > 1 and _time(evidence['finished_at']) < _time(state['created_at']):
                raise DomainError('The changed rule requires evidence collected after its revision.')
            if not state:
                self.storage.conn.execute('INSERT INTO governance_rule_state VALUES(?,?,?,?,?)', (rule_id, session_id, rule.version, 30, now()))
            version = state['evidence_version'] if state else rule.version
            previous = self.storage.conn.execute('SELECT * FROM governance_observations WHERE rule_id=? AND rule_version=? AND test_run_id=?',
                                                 (rule_id, version, test_run_id)).fetchone()
            if previous:
                if previous['supports'] != int(supports) or previous['reason'] != reason:
                    raise Conflict('This evidence already has a different observation.')
                return self._stats(rule)
            self.storage.conn.execute('INSERT INTO governance_observations VALUES(?,?,?,?,?,?,?,?)',
                (uid('observation'), rule_id, version, test_run_id, int(supports), reason, session_id, now()))
            self.storage.audit(rule.project_id, session_id, 'rule.observed', rule_id,
                               {'version': version, 'test_run_id': test_run_id, 'supports': supports, 'reason': reason})
            return self._stats(rule)

    def pause_task(self, task_id, reason):
        with self.storage.transaction():
            reason = _required(reason)
            task = self.storage.get_task(task_id)
            if not task:
                raise DomainError('Task not found.', 'not_found', 404)
            if task.status != TaskStatus.PAUSED:
                self.storage.update_task_status(task_id, TaskStatus.PAUSED)
                self.storage.conn.execute('UPDATE governance_task_pauses SET reason=? WHERE task_id=?', (reason, task_id))
                self.storage.audit(task.project_id, 'human', 'task.paused', task_id, {'reason': reason})
            return self.storage.get_task(task_id)

    def resume_task(self, task_id, reason):
        with self.storage.transaction():
            reason = _required(reason)
            task = self.storage.get_task(task_id)
            if not task:
                raise DomainError('Task not found.', 'not_found', 404)
            if task.status != TaskStatus.PAUSED:
                raise Conflict('Only paused tasks can be resumed.')
            prior = self.storage.conn.execute('SELECT previous_status FROM governance_task_pauses WHERE task_id=?', (task_id,)).fetchone()
            if not prior:
                raise Conflict('Pause provenance missing; restore task state explicitly after review.')
            self.storage.update_task_status(task_id, TaskStatus(prior['previous_status']))
            self.storage.audit(task.project_id, 'human', 'task.resumed', task_id, {'reason': reason, 'state': prior['previous_status']})
            return self.storage.get_task(task_id)

    def record_test_run(self, *, session_id, request_id, command, exit_code, stdout='', stderr='',
                        started_at, finished_at, paths):
        if not command or len(command) > 200 or any(not isinstance(x, str) or len(x) > 10000 for x in command):
            raise DomainError('command must be an argv list with at most 200 bounded strings.')
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise DomainError('exit_code must be the actual integer process result.')
        _required(request_id, 'request_id', 200)
        if len(stdout) + len(stderr) > 200000:
            raise DomainError('Test output exceeds 200000 characters; submit a bounded excerpt and retain the full client log.')
        try:
            start, finish = _time(started_at), _time(finished_at)
        except (ValueError, AttributeError, TypeError) as exc:
            raise DomainError('Test timestamps must be ISO timestamps.') from exc
        if finish < start or (finish - datetime.utcnow()).total_seconds() > 300:
            raise DomainError('Test timestamp range is invalid or in the future.')
        if not paths or len(paths) > 500:
            raise DomainError('At least one affected project path must accompany test evidence.')
        normalized = list(dict.fromkeys(relative_path(p) for p in paths))
        payload = {'command': command, 'exit_code': exit_code, 'stdout': stdout, 'stderr': stderr,
                   'started_at': start.isoformat(), 'finished_at': finish.isoformat(), 'paths': normalized}
        with self.storage.transaction():
            session = self._session(session_id)
            previous = self.storage.conn.execute('SELECT * FROM governance_test_runs WHERE session_id=? AND request_id=?',
                                                 (session_id, request_id)).fetchone()
            if previous:
                if previous['request_hash'] != _hash(payload):
                    raise Conflict('Test request_id reused with different evidence.')
                return self._test_run(previous)
            repeated_evidence = self.storage.conn.execute('SELECT * FROM governance_test_runs WHERE session_id=? AND request_hash=?',
                                                          (session_id, _hash(payload))).fetchone()
            if repeated_evidence:
                return self._test_run(repeated_evidence)
            run_id, command_hash = uid('test'), _hash(command)
            self.storage.conn.execute('''INSERT INTO governance_test_runs
                (id,project_id,task_id,session_id,request_id,request_hash,command_json,command_hash,exit_code,
                 stdout,stderr,started_at,finished_at,paths_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (run_id, session['project_id'], session['task_id'], session_id, request_id, _hash(payload),
                 _json(command), command_hash, exit_code, stdout, stderr, start.isoformat(), finish.isoformat(),
                 _json(normalized), now()))
            self.storage.audit(session['project_id'], session_id, 'test.recorded', run_id,
                               {'exit_code': exit_code, 'command': command, 'source': 'client_reported'})
            self._reflect_test(session, run_id, command_hash)
            return self._test_run(self.storage.conn.execute('SELECT * FROM governance_test_runs WHERE id=?', (run_id,)).fetchone())

    @staticmethod
    def _test_run(row):
        result = dict(row)
        result['command'] = json.loads(result.pop('command_json'))
        result['paths'] = json.loads(result.pop('paths_json'))
        result.pop('request_hash', None)
        return result

    def _reflect_test(self, session, run_id, command_hash):
        runs = list(self.storage.conn.execute('''SELECT * FROM governance_test_runs
            WHERE session_id=? AND task_id=? AND command_hash=? ORDER BY rowid DESC''',
            (session['id'], session['task_id'], command_hash)))
        current = runs[0]
        if any(_time(r['finished_at']) > _time(current['finished_at']) for r in runs[1:]):
            return  # A late report cannot rewrite an already observed recovery sequence.
        open_reflection = self.storage.conn.execute('''SELECT * FROM governance_reflections
            WHERE session_id=? AND task_id=? AND command_hash=? AND status='open' ORDER BY rowid DESC LIMIT 1''',
            (session['id'], session['task_id'], command_hash)).fetchone()
        if current['exit_code'] != 0:
            failures = []
            for run in runs:
                if run['exit_code'] == 0:
                    break
                failures.append(run['id'])
            if len(failures) < 2:
                return
            if open_reflection:
                self.storage.conn.execute('UPDATE governance_reflections SET failure_ids_json=?,updated_at=? WHERE id=?',
                                          (_json(failures), now(), open_reflection['id']))
            else:
                reflection_id = uid('reflection')
                self.storage.conn.execute('''INSERT INTO governance_reflections
                    (id,project_id,task_id,session_id,command_hash,status,failure_ids_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,'open',?,?,?)''',
                    (reflection_id, session['project_id'], session['task_id'], session['id'], command_hash, _json(failures), now(), now()))
                self.storage.audit(session['project_id'], session['id'], 'reflection.required', reflection_id,
                                   {'failure_run_ids': failures, 'trigger': 'two_consecutive_failed_runs'})
        elif open_reflection:
            failures = json.loads(open_reflection['failure_ids_json'])
            command = json.loads(current['command_json'])
            path = json.loads(current['paths_json'])[0]
            evidence_text = (f"Recorded test recovery: {json.dumps(command, ensure_ascii=False)} returned exit code 0 "
                f"after {len(failures)} consecutive recorded failures. Failure evidence: {', '.join(failures)}. "
                f"Recovery evidence: {run_id}. Outcomes were reported by session {session['id']}; "
                "the passing command alone does not establish the root cause.")
            if open_reflection['analysis']:
                evidence_text += '\nAgent root-cause assessment: ' + open_reflection['analysis']
            finding = self.storage.create_finding(Finding(id=uid('finding'), project_id=session['project_id'],
                task_id=session['task_id'], session_id=session['id'], target_path=path,
                finding_text=evidence_text, suggested_priority=Priority.P2, source='agent'))
            self.storage.conn.execute('''UPDATE governance_reflections SET status='recovered', recovery_run_id=?,
                finding_id=?,updated_at=? WHERE id=?''', (run_id, finding.id, now(), open_reflection['id']))
            self.storage.audit(session['project_id'], session['id'], 'reflection.recovered', open_reflection['id'],
                               {'finding_id': finding.id, 'recovery_run_id': run_id, 'failure_run_ids': failures})

    def explain_reflection(self, *, session_id, reflection_id, analysis):
        with self.storage.transaction():
            session = self._session(session_id)
            row = self.storage.conn.execute('SELECT * FROM governance_reflections WHERE id=?', (reflection_id,)).fetchone()
            if not row or row['session_id'] != session_id or row['task_id'] != session['task_id']:
                raise DomainError('Reflection does not belong to this session and task.', 'not_found', 404)
            analysis = _required(analysis, 'analysis')
            self.storage.conn.execute('UPDATE governance_reflections SET analysis=?,updated_at=? WHERE id=?', (analysis, now(), reflection_id))
            # Keep observation and agent interpretation explicitly distinct in retrievable memory.
            if row['finding_id']:
                finding = self.storage.conn.execute('SELECT finding_text FROM findings WHERE id=?', (row['finding_id'],)).fetchone()
                base = finding['finding_text'].split('\nAgent root-cause assessment:')[0]
                self.storage.conn.execute('UPDATE findings SET finding_text=? WHERE id=?',
                                          (base + '\nAgent root-cause assessment: ' + analysis, row['finding_id']))
            self.storage.audit(session['project_id'], session_id, 'reflection.explained', reflection_id, {'analysis': analysis})
            return dict(self.storage.conn.execute('SELECT * FROM governance_reflections WHERE id=?', (reflection_id,)).fetchone())

    def cleanup_session(self, session_id, request_id='automatic-close', close=True):
        with self.storage.transaction():
            _required(request_id, 'request_id', 200)
            session = self._session(session_id, active=False, task_required=False)
            previous = self.storage.conn.execute('SELECT * FROM governance_cleanups WHERE session_id=?', (session_id,)).fetchone()
            if previous:
                result = json.loads(previous['result_json'])
                if close and result['closed']:
                    self.storage.conn.execute("UPDATE agent_sessions SET state='closed',last_seen_at=? WHERE id=?", (now(), session_id))
                if result['closed'] or (not close and previous['request_id'] == request_id):
                    return {**result, 'duplicate': True}
            retained, revoked, review = [], [], []
            for row in self.storage.conn.execute('SELECT rule_id FROM governance_rule_state WHERE session_id=?', (session_id,)).fetchall():
                rule = self.storage.get_rule(row['rule_id'])
                if rule.status == RuleStatus.DRAFT:
                    self.storage.update_rule_status(rule.id, RuleStatus.REVOKED, rule.version, session_id,
                                                    'Session epilogue: unvalidated observation retired')
                    revoked.append(rule.id)
                elif rule.status == RuleStatus.ACTIVE:
                    retained.append(rule.id)
                    if self._stats(rule)['stage'] == 'validated':
                        review.append(rule.id)
            distillation_id = None
            if session['task_id']:
                distillation_id = queue_distillation(self.storage, session['project_id'], session['task_id'],
                                                      'session_cleanup', 'session:' + session_id)
            result = {'session_id': session_id, 'retained_rule_ids': retained, 'revoked_rule_ids': revoked,
                      'promotion_review_rule_ids': review, 'distillation_request_id': distillation_id,
                      'closed': bool(close), 'duplicate': False}
            if close:
                self.storage.conn.execute("UPDATE agent_sessions SET state='closed',last_seen_at=? WHERE id=?", (now(), session_id))
            self.storage.conn.execute('INSERT OR REPLACE INTO governance_cleanups VALUES(?,?,?,?)', (session_id, request_id, _json(result), now()))
            self.storage.audit(session['project_id'], session_id, 'session.cleaned', session_id, result)
            return result

    def process_pending_distillations(self, limit=20):
        """Safe to retry after crashes: the intelligence queue deduplicates request_id."""
        if self.intelligence is None:
            try:
                from .intelligence import IntelligenceService
                intelligence = IntelligenceService(self.storage)
            except ImportError:
                return []
        else:
            intelligence = self.intelligence
        # Surface the actual downstream job state without inventing success or
        # silently re-running a provider job the human has not chosen to retry.
        if hasattr(intelligence, 'get_job'):
            with self.storage.transaction(write=False):
                dispatched = [dict(r) for r in self.storage.conn.execute('''SELECT * FROM governance_distill_requests
                    WHERE job_id IS NOT NULL AND status IN ('queued','running','failed') LIMIT ?''', (limit,))]
            for entry in dispatched:
                try:
                    job = intelligence.get_job(entry['job_id'])
                    job_state = job.get('status', 'queued')
                    if job_state in ('queued', 'running', 'completed', 'failed'):
                        with self.storage.transaction():
                            self.storage.conn.execute('UPDATE governance_distill_requests SET status=?,error=?,updated_at=? WHERE id=?',
                                (job_state, _json(job.get('error')) if job.get('error') else None, now(), entry['id']))
                except DomainError:
                    pass  # Keep the durable job pointer for operator inspection.
        with self.storage.transaction(write=False):
            rows = [dict(r) for r in self.storage.conn.execute('''SELECT * FROM governance_distill_requests
                WHERE status IN ('pending','dispatch_failed') ORDER BY created_at LIMIT ?''', (limit,))]
        results = []
        for row in rows:
            try:
                with self.storage.transaction(write=False):
                    workspace = None
                    if row['source_key'].startswith('session:'):
                        workspace = self.storage.conn.execute('SELECT worktree_id FROM agent_sessions WHERE id=?',
                                                             (row['source_key'][8:],)).fetchone()
                    if workspace is None:
                        workspace = self.storage.conn.execute('''SELECT worktree_id FROM agent_sessions
                            WHERE project_id=? AND task_id=? ORDER BY last_seen_at DESC LIMIT 1''',
                            (row['project_id'], row['task_id'])).fetchone()
                job = intelligence.enqueue(kind='distill', project_id=row['project_id'], task_id=row['task_id'],
                                           request_id=row['id'], worktree_id=workspace['worktree_id'] if workspace else None)
                job_id = job.get('id') or job.get('job_id')
                if not job_id:
                    raise DomainError('Distillation queue returned no durable job id.')
                with self.storage.transaction():
                    self.storage.conn.execute("UPDATE governance_distill_requests SET status='queued',job_id=?,error=NULL,updated_at=? WHERE id=?",
                                              (job_id, now(), row['id']))
                results.append({'request_id': row['id'], 'job_id': job_id, 'status': 'queued'})
            except Exception as exc:
                with self.storage.transaction():
                    self.storage.conn.execute("UPDATE governance_distill_requests SET status='dispatch_failed',error=?,updated_at=? WHERE id=?",
                                              (str(exc)[:2000], now(), row['id']))
                results.append({'request_id': row['id'], 'status': 'dispatch_failed', 'error': str(exc)[:2000]})
        return results

    def _validate_refs(self, project_id, refs):
        allowed = {'rule': 'rules', 'finding': 'findings', 'issue': 'agent_issues', 'test_run': 'governance_test_runs'}
        normalized = []
        for ref in refs:
            kind = ref.get('kind')
            if kind not in allowed:
                raise DomainError('Unknown proposal source kind.')
            row = self.storage.conn.execute(f'SELECT * FROM {allowed[kind]} WHERE id=?', (ref.get('id'),)).fetchone()
            if not row or row['project_id'] != project_id:
                raise DomainError('Proposal source is missing or belongs to another project.')
            if 'source' in row.keys() and row['source'] == 'demo':
                raise DomainError('Demo records cannot be used as proposal evidence.')
            item = {'kind': kind, 'id': row['id']}
            if kind == 'rule':
                if ref.get('version') != row['version']:
                    raise Conflict('Source rule version changed.')
                item['version'] = row['version']
            normalized.append(item)
        return normalized

    def _validate_change(self, project_id, change):
        allowed = {'action', 'rule_id', 'expected_version', 'title', 'content_points', 'scope_patterns', 'priority', 'source_rule_ids'}
        if set(change) - allowed:
            raise DomainError('Unsupported structured change fields.')
        action = change.get('action')
        if action not in ('create', 'update', 'merge', 'revoke'):
            raise DomainError('Structured change action must be create, update, merge or revoke.')
        rule = None
        if action != 'create':
            rule = self.storage.get_rule(change.get('rule_id'))
            if not rule or rule.project_id != project_id:
                raise DomainError('Target rule is missing or belongs to another project.')
            if not isinstance(change.get('expected_version'), int) or change['expected_version'] != rule.version:
                raise Conflict('Target rule version changed; refresh the proposed change.')
        elif change.get('rule_id') or change.get('expected_version'):
            raise DomainError('A create change cannot target an existing rule.')
        if action != 'revoke':
            self._validate_content(change.get('title', rule.title if rule else ''),
                                   change.get('content_points', rule.content_points if rule else []),
                                   change.get('scope_patterns', rule.scope_patterns if rule else []))
            Priority(change.get('priority', rule.priority if rule else 'P1'))
        for rid in change.get('source_rule_ids', []):
            source = self.storage.get_rule(rid)
            if not source or source.project_id != project_id:
                raise DomainError('Merge sources must belong to the same project.')
        if action == 'merge' and (not change.get('source_rule_ids') or rule.lifecycle != Lifecycle.LONG_TERM):
            raise DomainError('Merge needs source_rule_ids and an existing long-term target.')
        return rule

    def propose_change(self, project_id, *, change, reason, source_refs=None, task_id=None):
        with self.storage.transaction():
            self.storage.validate_scope(project_id, task_id)
            reason = _required(reason)
            self._validate_change(project_id, change)
            refs = self._validate_refs(project_id, source_refs or [])
            existing_refs = {(r['kind'], r['id']) for r in refs}
            for rid in change.get('source_rule_ids', []):
                if ('rule', rid) not in existing_refs:
                    source = self.storage.get_rule(rid)
                    refs.append({'kind': 'rule', 'id': rid, 'version': source.version})
            proposal_id = uid('proposal')
            self.storage.conn.execute('''INSERT INTO governance_proposals
                (id,project_id,task_id,change_json,source_refs_json,reason,created_at) VALUES(?,?,?,?,?,?,?)''',
                (proposal_id, project_id, task_id, _json(change), _json(refs), reason, now()))
            self.storage.audit(project_id, 'proposal', 'governance.proposed', proposal_id, {'source_refs': refs, 'change': change, 'reason': reason})
            return self._proposal(self.storage.conn.execute('SELECT * FROM governance_proposals WHERE id=?', (proposal_id,)).fetchone())

    @staticmethod
    def _proposal(row):
        result = dict(row)
        result['change'] = json.loads(result.pop('change_json'))
        result['source_refs'] = json.loads(result.pop('source_refs_json'))
        result['result'] = json.loads(result.pop('result_json') or 'null')
        return result

    def _apply_change(self, project_id, change, actor, reason):
        original = self._validate_change(project_id, change)
        if change['action'] == 'create':
            # Promotions are contracts; temporary rules use the task-bound endpoint.
            result = self.storage.create_rule(Rule(id=uid('rule'), project_id=project_id, title=change['title'],
                content_points=change['content_points'], scope_patterns=change['scope_patterns'],
                priority=Priority(change.get('priority', 'P1')), lifecycle=Lifecycle.LONG_TERM,
                status=RuleStatus.ACTIVE, created_by=actor))
        elif change['action'] == 'revoke':
            self.storage.update_rule_status(original.id, RuleStatus.REVOKED, original.version, actor, reason)
            result = self.storage.get_rule(original.id)
        else:
            result = self.storage.update_rule_content(original.id, change.get('title', original.title),
                change.get('content_points', original.content_points), change.get('scope_patterns', original.scope_patterns),
                Priority(change.get('priority', original.priority)), reason, actor, original.version)
        return result

    def apply_proposal(self, proposal_id, *, reviewed, reviewer='human', reason):
        with self.storage.transaction():
            if reviewed is not True:
                raise DomainError('Review the exact structured change before applying.', 'review_required', 403)
            reason, reviewer = _required(reason), _required(reviewer, 'reviewer', 200)
            row = self.storage.conn.execute('SELECT * FROM governance_proposals WHERE id=?', (proposal_id,)).fetchone()
            if not row:
                raise DomainError('Proposal not found.', 'not_found', 404)
            if row['status'] == 'applied':
                return {**json.loads(row['result_json']), 'duplicate': True}
            if row['status'] != 'pending':
                raise Conflict('Only pending proposals can be applied.')
            change, refs = json.loads(row['change_json']), json.loads(row['source_refs_json'])
            self._validate_refs(row['project_id'], refs)
            result = self._apply_change(row['project_id'], change, 'human:' + reviewer, reason)
            response = {'proposal_id': proposal_id, 'rule': result.model_dump(mode='json'), 'source_refs': refs, 'duplicate': False}
            self.storage.conn.execute("UPDATE governance_proposals SET status='applied',result_json=?,reviewed_at=?,reviewer=? WHERE id=?",
                                      (_json(response), now(), reviewer, proposal_id))
            self.storage.audit(row['project_id'], 'human:' + reviewer, 'governance.applied', proposal_id,
                               {'rule_id': result.id, 'version': result.version, 'source_refs': refs, 'reason': reason})
            return response

    def reject_proposal(self, proposal_id, *, reviewer='human', reason):
        with self.storage.transaction():
            reason, reviewer = _required(reason), _required(reviewer, 'reviewer', 200)
            row = self.storage.conn.execute('SELECT * FROM governance_proposals WHERE id=?', (proposal_id,)).fetchone()
            if not row:
                raise DomainError('Proposal not found.', 'not_found', 404)
            if row['status'] == 'applied':
                raise Conflict('Applied proposals cannot be rejected; propose a new version.')
            self.storage.conn.execute("UPDATE governance_proposals SET status='rejected',reviewed_at=?,reviewer=? WHERE id=?",
                                      (now(), reviewer, proposal_id))
            self.storage.audit(row['project_id'], 'human:' + reviewer, 'governance.rejected', proposal_id, {'reason': reason})
            return {'proposal_id': proposal_id, 'status': 'rejected'}

    def apply_issue_suggestion(self, issue_id, *, reviewed, change, reason, reviewer='human'):
        with self.storage.transaction():
            if reviewed is not True:
                raise DomainError('Review the exact structured change before applying.', 'review_required', 403)
            row = self.storage.conn.execute('SELECT * FROM agent_issues WHERE id=?', (issue_id,)).fetchone()
            if not row or row['source'] == 'demo':
                raise DomainError('Issue not found.', 'not_found', 404)
            if row['status'] != 'open':
                raise Conflict('Only open issues can have a suggestion applied.')
            proposal = self.propose_change(row['project_id'], change=change, reason=reason,
                                          source_refs=[{'kind': 'issue', 'id': issue_id}])
            result = self.apply_proposal(proposal['id'], reviewed=reviewed, reviewer=reviewer, reason=reason)
            self.storage.resolve_issue(issue_id)
            self.storage.audit(row['project_id'], 'human:' + reviewer, 'issue.suggestion_applied', issue_id,
                               {'proposal_id': proposal['id'], 'rule_id': result['rule']['id'], 'version': result['rule']['version']})
            return {**result, 'issue_id': issue_id, 'issue_status': 'resolved'}

    def set_policy(self, rule_id, *, expected_version, spec, reviewed, reviewer='human'):
        """Bind an explicit, machine-checkable policy to one reviewed rule version."""
        with self.storage.transaction():
            if reviewed is not True:
                raise DomainError('Executable policy requires human review.', 'review_required', 403)
            rule = self.storage.get_rule(rule_id)
            if not rule:
                raise DomainError('Rule not found.', 'not_found', 404)
            if expected_version != rule.version:
                raise Conflict('Rule version changed.')
            kind = spec.get('kind')
            if kind not in ('forbid_path_changes', 'forbid_added_literal', 'require_added_literal'):
                raise DomainError('Unsupported policy kind.')
            if set(spec) - {'kind', 'paths', 'literal'}:
                raise DomainError('Unsupported policy fields.')
            paths = spec.get('paths', rule.scope_patterns)
            if not paths or len(paths) > 100:
                raise DomainError('Policy requires bounded path patterns.')
            paths = [relative_path(p, pattern=True) for p in paths]
            normalized = {'kind': kind, 'paths': paths}
            if kind != 'forbid_path_changes':
                normalized['literal'] = _required(spec.get('literal'), 'literal', 10000)
            self.storage.conn.execute('INSERT OR REPLACE INTO governance_policies VALUES(?,?,?,?,?)',
                                      (rule_id, rule.version, _json(normalized), _required(reviewer, 'reviewer', 200), now()))
            self.storage.audit(rule.project_id, 'human:' + reviewer, 'policy.reviewed', rule_id,
                               {'version': rule.version, 'spec': normalized})
            return {'rule_id': rule_id, 'rule_version': rule.version, 'spec': normalized}

    @staticmethod
    def _diff_files(diff):
        """Collect unified-diff additions by target path; reject ambiguous filenames."""
        files, current, line = {}, None, 0
        for text in diff.splitlines():
            if text.startswith('+++ '):
                path = text[4:].split('\t', 1)[0]
                if path == '/dev/null':
                    current = None
                    continue
                if path.startswith('b/'):
                    path = path[2:]
                current = relative_path(path)
                files.setdefault(current, [])
            elif text.startswith('--- '):
                path = text[4:].split('\t', 1)[0]
                if path != '/dev/null':
                    if path.startswith('a/'):
                        path = path[2:]
                    files.setdefault(relative_path(path), [])
            elif text.startswith('@@'):
                import re
                header = re.search(r'\+(\d+)', text)
                line = int(header.group(1)) if header else 0
            elif current and text.startswith('+'):
                files[current].append({'line': line, 'text': text[1:]})
                line += 1
            elif current and text.startswith(' '):
                line += 1
        return files

    def _deterministic_checks(self, rules, files, diff_files, diff):
        checks = []
        for rule in rules:
            row = self.storage.conn.execute('SELECT * FROM governance_policies WHERE rule_id=? AND rule_version=?',
                                             (rule.id, rule.version)).fetchone()
            if not row:
                continue
            spec = json.loads(row['spec_json'])
            matched = [p for p in files if any(self.context.matcher.matches_pattern(pat, p) for pat in spec['paths'])]
            if not matched:
                continue
            evidence, verdict = [], 'pass'
            if spec['kind'] == 'forbid_path_changes':
                evidence = [{'path': p, 'line': 0, 'excerpt': 'Path is listed among proposed changes'} for p in matched]
                verdict = 'violation'
            elif not diff:
                verdict = 'unverified'
            elif spec['kind'] == 'forbid_added_literal':
                evidence = [{'path': p, 'line': entry['line'], 'excerpt': entry['text']}
                            for p in matched for entry in diff_files.get(p, []) if spec['literal'] in entry['text']]
                verdict = 'violation' if evidence else 'unverified' if any(p not in diff_files for p in matched) else 'pass'
            else:
                missing = [p for p in matched if p in diff_files and not any(spec['literal'] in entry['text'] for entry in diff_files[p])]
                evidence = [{'path': p, 'line': 0, 'excerpt': 'Required literal absent from supplied added lines'} for p in missing]
                verdict = 'violation' if missing else 'unverified' if any(p not in diff_files for p in matched) else 'pass'
            checks.append({'rule_id': rule.id, 'rule_version': rule.version, 'priority': rule.priority.value,
                           'check_kind': spec['kind'], 'verdict': verdict, 'evidence': evidence,
                           'basis': 'human_reviewed_explicit_policy', 'spec': spec})
        return checks

    def preflight(self, *, session_id, request_id, files, plan, diff=''):
        _required(plan, 'plan', 50000)
        _required(request_id, 'request_id', 200)
        if not files or len(files) > 500 or len(diff) > 300000:
            raise DomainError('Preflight requires 1 to 500 files and a diff under 300000 characters.')
        normalized = list(dict.fromkeys(relative_path(p) for p in files))
        diff_files = self._diff_files(diff)
        # Diff paths cannot escape or silently evade the caller's declared scope.
        for path in diff_files:
            if path not in normalized:
                normalized.append(path)
        payload = {'files': normalized, 'plan': plan, 'diff': diff}
        with self.storage.transaction(write=False):
            session = self._session(session_id, task_required=False)
            rules = [r for r in self.context.eligible_rules(session['project_id'], session['task_id'])
                     if any(any(self.context.matcher.matches_pattern(pattern, path) for pattern in r.scope_patterns) for path in normalized)]
            snapshot = [{'rule_id': r.id, 'rule_version': r.version} for r in rules]
            previous = self.storage.conn.execute('SELECT * FROM governance_preflights WHERE session_id=? AND request_id=?',
                                                 (session_id, request_id)).fetchone()
            if previous:
                if previous['input_hash'] != _hash(payload):
                    raise Conflict('Preflight request_id reused with different input.')
                old = json.loads(previous['result_json'])
                if old['rules_checked'] != snapshot or old.get('task_id') != session['task_id']:
                    return {**old, 'decision': 'review', 'stale': True,
                            'limitations': old['limitations'] + ['Applicable rules or task changed since this assessment; request a new preflight.']}
                return {**old, 'duplicate': True}
            deterministic = self._deterministic_checks(rules, normalized, diff_files, diff)
        # Provider inference deliberately occurs outside the DB transaction.
        semantic, limitations = None, []
        if rules:
            try:
                intelligence = self.intelligence
                if intelligence is None:
                    from .intelligence import IntelligenceService
                    intelligence = IntelligenceService(self.storage)
                semantic = intelligence.semantic_assess(session['project_id'], files=normalized, plan=plan,
                    diff=diff, rules=rules, worktree_id=session['worktree_id'])
                if semantic.get('decision') not in ('allow', 'review', 'block'):
                    raise DomainError('Semantic provider returned an invalid decision.', 'provider_response_invalid')
            except (DomainError, ImportError) as exc:
                semantic = {'decision': 'review', 'violations': [], 'reasoning': 'Semantic assessment unavailable.',
                            'error': getattr(exc, 'code', 'provider_unavailable'), 'limitations': [str(exc)]}
            limitations.extend(semantic.get('limitations', []))
        else:
            semantic = {'decision': 'allow', 'violations': [], 'reasoning': 'No applicable active rules for these paths.',
                        'limitations': ['No rule-based assurance is available for ungoverned paths.']}
            limitations.extend(semantic['limitations'])
        hard_checks = [c for c in deterministic if c['priority'] == 'P0' and c['verdict'] == 'violation']
        violations = semantic.get('violations', [])
        rule_map = {r.id: r for r in rules}
        grounded_p0 = [v for v in violations if v.get('rule_id') in rule_map
                       and rule_map[v['rule_id']].priority == Priority.P0
                       and v.get('rule_version') == rule_map[v['rule_id']].version
                       and v.get('severity') == 'violation' and v.get('evidence')
                       and ((v.get('diff_excerpt') and v['diff_excerpt'] in diff)
                            or (v.get('plan_excerpt') and v['plan_excerpt'] in plan))]
        decision = semantic['decision']
        if hard_checks or grounded_p0:
            decision = 'block'
        elif decision == 'block':
            decision = 'review'
            limitations.append('No grounded P0 violation was returned; a model-only block was downgraded for review.')
        elif any(c['verdict'] != 'pass' for c in deterministic):
            decision = 'review'
        result = {'id': uid('preflight'), 'session_id': session_id, 'task_id': session['task_id'], 'request_id': request_id,
                  'decision': decision, 'rules_checked': snapshot, 'checks': deterministic, 'semantic': semantic,
                  'limitations': limitations + ['Assesses the supplied plan and diff; does not execute or certify the code.'],
                  'stale': False, 'duplicate': False}
        with self.storage.transaction():
            current_session = self._session(session_id, task_required=False)
            current_rules = [r for r in self.context.eligible_rules(session['project_id'], current_session['task_id'])
                             if any(any(self.context.matcher.matches_pattern(pattern, path) for pattern in r.scope_patterns) for path in normalized)]
            if current_session['task_id'] != session['task_id'] or snapshot != [{'rule_id': r.id, 'rule_version': r.version} for r in current_rules]:
                result['decision'], result['stale'] = 'review', True
                result['limitations'].append('Applicable rules or task changed while the assessment ran; retry.')
            concurrent = self.storage.conn.execute('SELECT * FROM governance_preflights WHERE session_id=? AND request_id=?',
                                                   (session_id, request_id)).fetchone()
            if concurrent:
                if concurrent['input_hash'] != _hash(payload):
                    raise Conflict('Preflight request_id reused with different input.')
                return {**json.loads(concurrent['result_json']), 'duplicate': True}
            self.storage.conn.execute('INSERT INTO governance_preflights VALUES(?,?,?,?,?,?,?,?)',
                (result['id'], session['project_id'], session_id, request_id, _hash(payload), _json(payload), _json(result), now()))
            self.storage.audit(session['project_id'], session_id, 'preflight.assessed', result['id'],
                               {'decision': result['decision'], 'rules_checked': snapshot, 'stale': result['stale']})
        return result

    def overview(self, project_id):
        with self.storage.transaction(write=False):
            self.storage.validate_scope(project_id)
            rules = [self._stats(r) for r in self.storage.list_rules(project_id, status=None)]
            reflections = []
            for row in self.storage.conn.execute('SELECT * FROM governance_reflections WHERE project_id=? ORDER BY created_at DESC', (project_id,)):
                item = dict(row)
                item['failure_run_ids'] = json.loads(item.pop('failure_ids_json'))
                reflections.append(item)
            return {'project_id': project_id, 'rules': rules, 'reflections': reflections,
                'proposals': [self._proposal(r) for r in self.storage.conn.execute(
                    'SELECT * FROM governance_proposals WHERE project_id=? ORDER BY created_at DESC', (project_id,))],
                'distillation_requests': [dict(r) for r in self.storage.conn.execute(
                    'SELECT * FROM governance_distill_requests WHERE project_id=? ORDER BY created_at DESC', (project_id,))],
                'test_runs': [self._test_run(r) for r in self.storage.conn.execute(
                    'SELECT * FROM governance_test_runs WHERE project_id=? ORDER BY rowid DESC LIMIT 100', (project_id,))],
                'confidence_definition': 'Beta(1,1) posterior from explicit observations, decayed by age; evidence strength, not truth probability.',
                'aging_policy': 'Stale knowledge is flagged for review; P0 and human contracts are never silently discarded.'}
