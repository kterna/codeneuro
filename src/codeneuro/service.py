"""Application rules shared by REST, MCP and CLI. No transport owns policy."""
import hashlib
import json
import socket
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from .database import Conflict, DomainError
from .matcher import ScopeMatcher
from .models import (ContextResolution, Finding, FindingStatus, Lifecycle, Priority,
                     RuleEvaluation, RuleStatus, TaskStatus, WorktreeInstance)
from .paths import workspace_file
from .synthesizer import ContextSynthesizer


def now():
    return datetime.utcnow().isoformat()


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


class ContextService:
    def __init__(self, storage):
        self.storage = storage
        self.matcher = ScopeMatcher()

    def _session(self, session_id, *, active=True):
        row = self.storage.conn.execute("SELECT * FROM agent_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise DomainError("Agent session not found; call codeneuro_start_session first.", "not_found", 404)
        if active and row['state'] != 'active':
            raise Conflict("Agent session has been closed.")
        return dict(row)

    def _workspace(self, project, workspace):
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise DomainError("Workspace must be an existing local directory.")
        roots = [Path(p).expanduser().resolve() for p in project.root_paths]
        def common_git(path):
            r = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--show-toplevel', '--git-common-dir'],
                               capture_output=True, text=True, timeout=5)
            values = r.stdout.strip().splitlines()
            return values[1] if r.returncode == 0 and len(values) == 2 and Path(values[0]).resolve() == path else None
        if root not in roots:
            common = common_git(root)
            if not common or not any(common_git(p) == common for p in roots if p.is_dir()):
                raise DomainError("Workspace is not a registered project root or a worktree of its Git repository.")
        return root

    def start_session(self, project_id, workspace_path, task_id=None, agent_client='MCP', debug=False):
        with self.storage.transaction():
            self.storage.validate_scope(project_id, task_id, require_active=True)
            project = self.storage.get_project(project_id)
            root = self._workspace(project, workspace_path)
            machine = socket.gethostname()
            wid = 'wt_' + hashlib.sha256(f'{project_id}\0{machine}\0{root}'.encode()).hexdigest()[:24]
            r = subprocess.run(['git', '-C', str(root), 'rev-parse', '--abbrev-ref', 'HEAD'],
                               capture_output=True, text=True, timeout=5)
            branch = r.stdout.strip() if r.returncode == 0 else ''
            self.storage.register_worktree_heartbeat(WorktreeInstance(
                id=wid, project_id=project_id, machine_name=machine, worktree_path=str(root),
                git_branch=branch, active_task_id=task_id, agent_client=agent_client))
            sid = uid('session')
            self.storage.conn.execute("INSERT INTO agent_sessions(id,project_id,worktree_id,task_id,agent_client,debug,created_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?)",
                                      (sid, project_id, wid, task_id, agent_client, int(debug), now(), now()))
            self.storage.audit(project_id, sid, 'session.started', sid, {'worktree_id': wid, 'task_id': task_id, 'client': agent_client})
            return self._session(sid)

    def close_session(self, session_id):
        with self.storage.transaction():
            session = self._session(session_id, active=False)
            self.storage.conn.execute("UPDATE agent_sessions SET state='closed',last_seen_at=? WHERE id=?", (now(), session_id))
            self.storage.audit(session['project_id'], session_id, 'session.closed', session_id, {})
            return {'session_id': session_id, 'state': 'closed'}

    def eligible_rules(self, project_id, task_id=None):
        self.storage.validate_scope(project_id, task_id)
        task = self.storage.get_task(task_id) if task_id else None
        effective_task = task_id if task and task.status in (TaskStatus.ACTIVE, TaskStatus.TESTING) else None
        return [r for r in self.storage.list_rules(project_id) if
                r.lifecycle == Lifecycle.LONG_TERM or (effective_task is not None and r.task_id == effective_task)]

    def resolve(self, *, file_path, project_id=None, task_id=None, session_id=None,
                request_id=None, max_chars=24000, debug=False):
        if not 512 <= max_chars <= 200000:
            raise DomainError("max_chars must be between 512 and 200000.")
        with self.storage.transaction(write=bool(session_id)):
            session, root = None, None
            if session_id:
                session = self._session(session_id)
                if project_id and project_id != session['project_id']:
                    raise DomainError("Session belongs to another project.")
                if task_id and task_id != session['task_id']:
                    raise DomainError("Task differs from the session's pinned task.")
                project_id, task_id, debug = session['project_id'], session['task_id'], bool(session['debug'])
                wt = self.storage.conn.execute("SELECT * FROM worktree_instances WHERE id=?", (session['worktree_id'],)).fetchone()
                root = wt['worktree_path']
            if not project_id:
                raise DomainError("project_id is required for a preview.")
            self.storage.validate_scope(project_id, task_id)
            if not root and Path(file_path).is_absolute():
                roots = self.storage.get_project(project_id).root_paths
                matches = [p for p in roots if Path(file_path).resolve().is_relative_to(Path(p).resolve())]
                if not matches:
                    raise DomainError("Absolute file path is outside this project.")
                root = max(matches, key=len)
            path = workspace_file(file_path, root)
            task = self.storage.get_task(task_id) if task_id else None
            effective_task = task_id if task and task.status in (TaskStatus.ACTIVE, TaskStatus.TESTING) else None
            request_json = json.dumps({'file': path, 'task': effective_task, 'max_chars': max_chars}, sort_keys=True)
            request_id = request_id or uid('request')
            if session:
                previous = self.storage.conn.execute("SELECT * FROM context_deliveries WHERE session_id=? AND request_id=?", (session_id, request_id)).fetchone()
                if previous:
                    if previous['request_json'] != request_json:
                        raise Conflict("request_id was already used with different input or task state.")
                    return ContextResolution.model_validate_json(previous['response_json'])
            rules = self.eligible_rules(project_id, effective_task)
            long_term, short_term = self.matcher.filter_rules(rules, path, effective_task)
            matched = sorted(long_term + short_term, key=lambda r: (r.priority.rank, r.id))
            known = set()
            if session:
                known = {(r['rule_id'], r['rule_version']) for r in self.storage.conn.execute(
                    "SELECT rule_id,rule_version FROM session_knowledge WHERE session_id=?", (session_id,))}
            reminders, omitted, full = [], [], []
            consumed = 600
            for rule in matched:
                ref = {'rule_id': rule.id, 'version': rule.version, 'title': rule.title, 'priority': rule.priority.value}
                if rule.priority != Priority.P0 and (rule.id, rule.version) in known:
                    if consumed + len(rule.title) + 100 <= max_chars:
                        reminders.append(ref)
                        consumed += len(rule.title) + 100
                    else:
                        omitted.append({**ref, 'reason': 'context_budget'})
                    continue
                cost = len(rule.title) + sum(len(p) for p in rule.content_points) + 120
                if rule.priority != Priority.P0 and consumed + cost > max_chars:
                    omitted.append({**ref, 'reason': 'context_budget'})
                    continue
                consumed += cost
                full.append(rule)
            # Findings belong to a task and session. Unreviewed discoveries from
            # another parallel agent must not become global instructions.
            findings = [f for f in self.storage.list_findings(project_id, FindingStatus.PENDING_REVIEW)
                        if effective_task and f.task_id == effective_task and
                        (not f.session_id or f.session_id == session_id) and
                        self.matcher.matches_pattern(f.target_path, path)]
            bounded = []
            for f in findings:
                if consumed + len(f.finding_text) + 100 <= max_chars:
                    bounded.append(f)
                    consumed += len(f.finding_text) + 100
            result = ContextSynthesizer.synthesize(file_path=path, project_id=project_id, task_id=effective_task,
                long_term_rules=[r for r in full if r.lifecycle == Lifecycle.LONG_TERM],
                short_term_rules=[r for r in full if r.lifecycle == Lifecycle.SHORT_TERM], findings=bounded, debug_mode=debug)
            result.session_id, result.mode = session_id, 'delivery' if session else 'preview'
            result.reminders, result.omitted_rules = reminders, omitted
            if reminders:
                result.rendered_markdown += '\n\n已确认知晓（当前会话、当前版本）：\n' + '\n'.join(
                    f"- {r['rule_id']} v{r['version']}: {r['title']}" for r in reminders)
            if omitted:
                result.rendered_markdown += f'\n\n有 {len(omitted)} 条非 P0 规则因上下文预算未下发；可提高 max_chars。'
            result.budget_exceeded = len(result.rendered_markdown) > max_chars
            if result.budget_exceeded:
                result.rendered_markdown += '\n\n注意：上下文超过目标预算；P0 约束始终完整保留。'
            if session:
                did = uid('delivery')
                result.delivery_id = did
                result.rendered_markdown = f'<!-- delivery_id={did} session_id={session_id} -->\n' + result.rendered_markdown
                self.storage.conn.execute("INSERT INTO context_deliveries VALUES(?,?,?,?,?,?,?)", (did, session_id, request_id, path, request_json, result.model_dump_json(), now()))
                for rule in full:
                    self.storage.conn.execute("INSERT INTO delivery_rules VALUES(?,?,?,?)", (did, rule.id, rule.version, 'full'))
                for ref in reminders:
                    self.storage.conn.execute("INSERT INTO delivery_rules VALUES(?,?,?,?)", (did, ref['rule_id'], ref['version'], 'reminder'))
                self.storage.increment_rule_hits([r.id for r in full] + [r['rule_id'] for r in reminders])
                self.storage.conn.execute("UPDATE agent_sessions SET last_seen_at=? WHERE id=?", (now(), session_id))
                self.storage.conn.execute("UPDATE worktree_instances SET last_heartbeat=?,current_file=?,is_online=1 WHERE id=?", (now(), path, session['worktree_id']))
                self.storage.audit(project_id, session_id, 'context.delivered', did, {'file_path': path, 'request_id': request_id})
                self.storage.log_telemetry_event(project_id, 'jit_hit', f'Agent context: {path}', {'delivery_id': did, 'session_id': session_id, 'rule_ids': [r.id for r in full]})
            return result

    def evaluate(self, *, session_id, delivery_id, rule_id, score, reason=''):
        with self.storage.transaction():
            session = self._session(session_id)
            if not session['debug']:
                raise DomainError("Debug feedback is disabled for this session.", 'debug_disabled', 403)
            receipt = self.storage.conn.execute("SELECT * FROM context_deliveries WHERE id=? AND session_id=?", (delivery_id, session_id)).fetchone()
            rule = self.storage.conn.execute("SELECT * FROM delivery_rules WHERE delivery_id=? AND rule_id=?", (delivery_id, rule_id)).fetchone()
            if receipt is None or rule is None:
                raise DomainError("Feedback must reference a rule actually delivered to this session.")
            previous = self.storage.conn.execute("SELECT * FROM rule_evaluations WHERE delivery_id=? AND rule_id=?", (delivery_id, rule_id)).fetchone()
            if previous:
                if previous['score'] != score or (previous['reason'] or '') != reason:
                    raise Conflict("This delivery already has different feedback for that rule.")
                return {'evaluation_id': previous['id'], 'score': score, 'duplicate': True}
            item = RuleEvaluation(id=uid('eval'), project_id=session['project_id'], rule_id=rule_id,
                score=score, reason=reason, session_id=session_id, delivery_id=delivery_id,
                rule_version=rule['rule_version'], file_path=receipt['file_path'], source='agent')
            self.storage.record_evaluation(item)
            if score == 0:
                self.storage.conn.execute("INSERT OR IGNORE INTO session_knowledge VALUES(?,?,?,?)", (session_id, rule_id, rule['rule_version'], now()))
            self.storage.audit(session['project_id'], session_id, 'rule.evaluated', item.id, {'delivery_id': delivery_id, 'rule_id': rule_id, 'version': rule['rule_version'], 'score': score})
            return {'evaluation_id': item.id, 'score': score, 'rule_version': rule['rule_version'], 'duplicate': False}

    def record_finding(self, session_id, target_path, text, priority='P1'):
        with self.storage.transaction():
            session = self._session(session_id)
            self.storage.validate_scope(session['project_id'], session['task_id'], require_active=True)
            if not session['task_id']:
                raise DomainError("Discoveries require a task-bound session.")
            wt = self.storage.conn.execute("SELECT * FROM worktree_instances WHERE id=?", (session['worktree_id'],)).fetchone()
            path = workspace_file(target_path, wt['worktree_path'])
            item = Finding(id=uid('finding'), project_id=session['project_id'], task_id=session['task_id'],
                           session_id=session_id, target_path=path, finding_text=text, suggested_priority=Priority(priority), source='agent')
            self.storage.create_finding(item)
            self.storage.audit(session['project_id'], session_id, 'finding.recorded', item.id, {'path': path})
            return item
