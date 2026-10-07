"""SQLite storage implementation with WAL mode, rule versioning, worktree fleet, and health engine."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from codeneuro.database import Transactional, atomic, DomainError, Conflict
from codeneuro.paths import relative_path
from codeneuro.migrations import migrate

from codeneuro.models import (
    AgentIssue,
    Finding,
    FindingStatus,
    HealthCheckReport,
    IssueStatus,
    IssueType,
    Lifecycle,
    Priority,
    Project,
    Proposal,
    Rule,
    RuleConflict,
    RuleEvaluation,
    RuleStatus,
    RuleVersion,
    Task,
    TaskStatus,
    WorktreeInstance,
)


class Storage(Transactional):
    def __init__(self, db_path: str = ":memory:"):
        self._setup_transactions()
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=15
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=15000")
        self._init_db()
        migrate(self)
        from .governance import ensure_schema
        ensure_schema(self)

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")

        cur.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            root_paths TEXT NOT NULL, -- JSON list
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rules (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            scope_patterns TEXT NOT NULL, -- JSON list
            priority TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            title TEXT NOT NULL,
            content_points TEXT NOT NULL, -- JSON list
            created_by TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            hit_count INTEGER DEFAULT 0,
            last_hit_at TEXT,
            avg_score REAL,
            eval_count INTEGER DEFAULT 0,
            zero_score_count INTEGER DEFAULT 0,
            one_score_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rule_versions (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            scope_patterns TEXT NOT NULL,
            priority TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            content_points TEXT NOT NULL,
            change_summary TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS worktree_instances (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            machine_name TEXT NOT NULL,
            worktree_path TEXT NOT NULL,
            git_branch TEXT NOT NULL,
            git_commit TEXT,
            active_task_id TEXT,
            current_file TEXT,
            agent_client TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL,
            is_online INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            session_id TEXT,
            target_path TEXT NOT NULL,
            finding_text TEXT NOT NULL,
            suggested_priority TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            target_component TEXT NOT NULL,
            proposed_contract TEXT NOT NULL,
            justification TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rule_evaluations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            score INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            reason TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_issues (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            issue_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            file_path TEXT NOT NULL,
            related_rule_ids TEXT NOT NULL, -- JSON list
            suggested_action TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS telemetry_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL, -- jit_hit | finding | issue | rule_edit | heartbeat
            summary TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_rules_task ON rules(task_id);
        CREATE INDEX IF NOT EXISTS idx_findings_project ON findings(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_evals_rule ON rule_evaluations(rule_id);
        CREATE INDEX IF NOT EXISTS idx_issues_project ON agent_issues(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_worktrees_proj ON worktree_instances(project_id);
        CREATE INDEX IF NOT EXISTS idx_events_proj ON telemetry_events(project_id, created_at DESC);
        """)

        columns = {r[1] for r in cur.execute("PRAGMA table_info(rules)")}
        for name, declaration in [("version", "INTEGER DEFAULT 1"), ("avg_score", "REAL"),
                                  ("eval_count", "INTEGER DEFAULT 0"), ("zero_score_count", "INTEGER DEFAULT 0"),
                                  ("one_score_count", "INTEGER DEFAULT 0")]:
            if name not in columns:
                cur.execute(f"ALTER TABLE rules ADD COLUMN {name} {declaration}")

    # --- Project Operations ---

    @atomic(write=True)
    def create_project(self, project: Project) -> Project:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO projects (id, name, description, root_paths, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                project.id,
                project.name,
                project.description,
                json.dumps(project.root_paths),
                project.created_at.isoformat(),
            ),
        )
        return project

    @atomic(write=False)
    def get_project(self, project_id: str) -> Optional[Project]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        row = cur.fetchone()
        if not row:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            root_paths=json.loads(row["root_paths"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @atomic(write=False)
    def list_projects(self) -> List[Project]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM projects ORDER BY created_at DESC")
        res = []
        for row in cur.fetchall():
            res.append(
                Project(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    root_paths=json.loads(row["root_paths"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    # --- Task Operations ---

    @atomic(write=True)
    def create_task(self, task: Task) -> Task:
        self.validate_scope(task.project_id)
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO tasks (id, project_id, title, description, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.project_id,
                task.title,
                task.description,
                task.status.value,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ),
        )
        return task

    @atomic(write=False)
    def get_task(self, task_id: str) -> Optional[Task]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        return Task(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @atomic(write=False)
    def list_tasks(self, project_id: str) -> List[Task]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        tasks = []
        for row in cur.fetchall():
            tasks.append(
                Task(
                    id=row["id"],
                    project_id=row["project_id"],
                    title=row["title"],
                    description=row["description"],
                    status=TaskStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            )
        return tasks

    @atomic(write=True)
    def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        from .governance import task_transition
        task_transition(self, task, status)
        self.conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status.value, datetime.utcnow().isoformat(), task_id))
        if status in (TaskStatus.RELEASED, TaskStatus.ARCHIVED):
            for rule in self.list_rules(task.project_id, task_id=task_id):
                if rule.lifecycle == Lifecycle.SHORT_TERM:
                    self.update_rule_status(rule.id, RuleStatus.DEPRECATED)
        self.audit(task.project_id, "human", "task.status", task_id, {"old": task.status.value, "new": status.value})
        return True

    # --- Rule Operations with Full Versioning & Snapshots ---

    @atomic(write=True)
    def create_rule(self, rule: Rule) -> Rule:
        rule.scope_patterns = [relative_path(p, pattern=True) for p in rule.scope_patterns]
        self.validate_scope(rule.project_id, rule.task_id, require_active=rule.status == RuleStatus.ACTIVE)
        if rule.lifecycle == Lifecycle.SHORT_TERM and not rule.task_id:
            raise DomainError("A short-term rule must belong to a task.")
        if rule.lifecycle == Lifecycle.LONG_TERM and rule.task_id:
            raise DomainError("A long-term rule cannot belong to a temporary task.")
        cur = self.conn.cursor()
        now_str = rule.created_at.isoformat()
        cur.execute(
            """INSERT INTO rules (id, project_id, task_id, scope_patterns, priority,
                                  lifecycle, title, content_points, created_by, status,
                                  version, hit_count, last_hit_at, avg_score, eval_count,
                                  zero_score_count, one_score_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.id,
                rule.project_id,
                rule.task_id,
                json.dumps(rule.scope_patterns),
                rule.priority.value,
                rule.lifecycle.value,
                rule.title,
                json.dumps(rule.content_points),
                rule.created_by,
                rule.status.value,
                rule.version,
                rule.hit_count,
                rule.last_hit_at.isoformat() if rule.last_hit_at else None,
                rule.avg_score,
                rule.eval_count,
                rule.zero_score_count,
                rule.one_score_count,
                now_str,
                rule.updated_at.isoformat(),
            ),
        )

        # Snapshot version 1
        ver_id = f"ver_{uuid.uuid4().hex}"
        cur.execute(
            """INSERT INTO rule_versions (id, rule_id, project_id, version_number, title,
                                          scope_patterns, priority, lifecycle, content_points,
                                          change_summary, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ver_id,
                rule.id,
                rule.project_id,
                rule.version,
                rule.title,
                json.dumps(rule.scope_patterns),
                rule.priority.value,
                rule.lifecycle.value,
                json.dumps(rule.content_points),
                "初始创建 (Initial commit)",
                rule.created_by,
                now_str,
            ),
        )
        self.conn.execute("UPDATE rule_versions SET status=?,task_id=? WHERE id=?", (rule.status.value, rule.task_id, ver_id))
        self.audit(rule.project_id, rule.created_by, "rule.created", rule.id, {"version": rule.version})
        return rule

    @atomic(write=True)
    def update_rule_content(
        self,
        rule_id: str,
        title: str,
        content_points: List[str],
        scope_patterns: List[str],
        priority: Priority,
        change_summary: str = "在线更新",
        operator: str = "user",
        expected_version: Optional[int] = None
    ) -> Optional[Rule]:
        rule = self.get_rule(rule_id)
        if not rule:
            return None

        if expected_version is not None and rule.version != expected_version:
            raise Conflict("Rule was changed by another client; reload before editing.")
        scope_patterns = [relative_path(v, pattern=True) for v in scope_patterns]
        new_version = (rule.version or 1) + 1
        now_str = datetime.utcnow().isoformat()
        cur = self.conn.cursor()

        cur.execute(
            """UPDATE rules SET title = ?, content_points = ?, scope_patterns = ?, priority = ?,
                                version = ?, updated_at = ?, avg_score=NULL, eval_count=0, zero_score_count=0, one_score_count=0 WHERE id = ?""",
            (
                title,
                json.dumps(content_points),
                json.dumps(scope_patterns),
                priority.value,
                new_version,
                now_str,
                rule_id,
            ),
        )

        # Record version snapshot
        ver_id = f"ver_{uuid.uuid4().hex}"
        cur.execute(
            """INSERT INTO rule_versions (id, rule_id, project_id, version_number, title,
                                          scope_patterns, priority, lifecycle, content_points,
                                          change_summary, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ver_id,
                rule.id,
                rule.project_id,
                new_version,
                title,
                json.dumps(scope_patterns),
                priority.value,
                rule.lifecycle.value,
                json.dumps(content_points),
                change_summary,
                operator,
                now_str,
            ),
        )
        self.conn.execute("UPDATE rule_versions SET status=?,task_id=? WHERE id=?", (rule.status.value, rule.task_id, ver_id))
        from .governance import rule_revision
        rule_revision(self, rule, new_version, title, content_points, scope_patterns, priority)
        self.audit(rule.project_id, operator, "rule.updated", rule_id, {"version": new_version, "reason": change_summary})
        return self.get_rule(rule_id)

    @atomic(write=True)
    def rollback_rule_version(self, rule_id: str, target_version: int, operator: str = "user", expected_version: Optional[int] = None) -> Optional[Rule]:
        row = self.conn.execute("SELECT * FROM rule_versions WHERE rule_id=? AND version_number=?", (rule_id, target_version)).fetchone()
        if row is None:
            return None
        current = self.get_rule(rule_id)
        self.validate_scope(current.project_id, row['task_id'])
        if row['status'] == 'active' and row['task_id']:
            if self.get_task(row['task_id']).status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict("A historical version cannot reactivate a rule for an inactive task.")
        result = self.update_rule_content(rule_id, row['title'], json.loads(row['content_points']), json.loads(row['scope_patterns']), Priority(row['priority']), f"Rollback to version {target_version}", operator, expected_version)
        self.conn.execute("UPDATE rules SET status=?,lifecycle=?,task_id=? WHERE id=?", (row['status'], row['lifecycle'], row['task_id'], rule_id))
        self.conn.execute("UPDATE rule_versions SET status=?,lifecycle=?,task_id=? WHERE rule_id=? AND version_number=?", (row['status'], row['lifecycle'], row['task_id'], rule_id, result.version))
        return self.get_rule(rule_id)

    @atomic(write=False)
    def list_rule_versions(self, rule_id: str) -> List[RuleVersion]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM rule_versions WHERE rule_id = ? ORDER BY version_number DESC",
            (rule_id,),
        )
        res = []
        for r in cur.fetchall():
            res.append(
                RuleVersion(
                    id=r["id"],
                    rule_id=r["rule_id"],
                    project_id=r["project_id"],
                    version_number=r["version_number"],
                    status=RuleStatus(r["status"]), task_id=r["task_id"],
                    title=r["title"],
                    scope_patterns=json.loads(r["scope_patterns"]),
                    priority=Priority(r["priority"]),
                    lifecycle=Lifecycle(r["lifecycle"]),
                    content_points=json.loads(r["content_points"]),
                    change_summary=r["change_summary"],
                    created_by=r["created_by"],
                    created_at=datetime.fromisoformat(r["created_at"]),
                )
            )
        return res

    @atomic(write=False)
    def get_rule(self, rule_id: str) -> Optional[Rule]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_rule(row)

    @atomic(write=False)
    def list_rules(
        self,
        project_id: str,
        task_id: Optional[str] = None,
        lifecycle: Optional[Lifecycle] = None,
        status: Optional[RuleStatus] = RuleStatus.ACTIVE,
    ) -> List[Rule]:
        query = "SELECT * FROM rules WHERE project_id = ?"
        params: List[Any] = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        if lifecycle:
            query += " AND lifecycle = ?"
            params.append(lifecycle.value)

        query += " ORDER BY priority ASC, created_at DESC"

        cur = self.conn.cursor()
        cur.execute(query, params)
        return [self._row_to_rule(r) for r in cur.fetchall()]

    @atomic(write=True)
    def update_rule_status(self, rule_id: str, status: RuleStatus, expected_version: Optional[int] = None,
                           operator: str = "user", reason: Optional[str] = None) -> bool:
        rule = self.get_rule(rule_id)
        if rule is None:
            return False
        if status == RuleStatus.ACTIVE and rule.task_id:
            self.validate_scope(rule.project_id, rule.task_id, require_active=True)
        if expected_version is not None and expected_version != rule.version:
            raise Conflict("Rule version changed.")
        if rule.status == status:
            return True
        updated = self.update_rule_content(rule_id, rule.title, rule.content_points, rule.scope_patterns, rule.priority,
                                           reason or f"Status: {rule.status.value} -> {status.value}",
                                           operator=operator, expected_version=rule.version)
        self.conn.execute("UPDATE rules SET status=? WHERE id=?", (status.value, rule_id))
        self.conn.execute("UPDATE rule_versions SET status=? WHERE rule_id=? AND version_number=?", (status.value, rule_id, updated.version))
        return True

    @atomic(write=True)
    def increment_rule_hits(self, rule_ids: List[str]):
        if not rule_ids:
            return
        placeholders = ",".join("?" for _ in rule_ids)
        now_str = datetime.utcnow().isoformat()
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE rules SET hit_count = hit_count + 1, last_hit_at = ? WHERE id IN ({placeholders})",
            [now_str] + rule_ids,
        )

    # --- Worktree Fleet Management ---

    @atomic(write=True)
    def register_worktree_heartbeat(self, wt: WorktreeInstance) -> WorktreeInstance:
        self.validate_scope(wt.project_id, wt.active_task_id)
        old = self.conn.execute("SELECT * FROM worktree_instances WHERE id=?", (wt.id,)).fetchone()
        if old and (old['project_id'],old['machine_name'],old['worktree_path']) != (wt.project_id,wt.machine_name,wt.worktree_path):
            raise Conflict("Worktree identity cannot be rebound to another project, machine or path.")
        cur = self.conn.cursor()
        now_str = datetime.utcnow().isoformat()
        cur.execute(
            """INSERT INTO worktree_instances (id, project_id, machine_name, worktree_path,
                                               git_branch, git_commit, active_task_id,
                                               current_file, agent_client, last_heartbeat, is_online)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                   git_branch = excluded.git_branch,
                   git_commit = excluded.git_commit,
                   active_task_id = excluded.active_task_id,
                   current_file = excluded.current_file,
                   agent_client = excluded.agent_client,
                   last_heartbeat = excluded.last_heartbeat,
                   is_online = 1""",
            (
                wt.id,
                wt.project_id,
                wt.machine_name,
                wt.worktree_path,
                wt.git_branch,
                wt.git_commit,
                wt.active_task_id,
                wt.current_file,
                wt.agent_client,
                now_str,
            ),
        )
        return wt

    @atomic(write=False)
    def list_worktrees(self, project_id: str) -> List[WorktreeInstance]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM worktree_instances WHERE source != 'demo' AND project_id = ? ORDER BY last_heartbeat DESC",
            (project_id,),
        )
        res = []
        for r in cur.fetchall():
            res.append(
                WorktreeInstance(
                    id=r["id"],
                    project_id=r["project_id"],
                    machine_name=r["machine_name"],
                    worktree_path=r["worktree_path"],
                    git_branch=r["git_branch"],
                    git_commit=r["git_commit"],
                    active_task_id=r["active_task_id"],
                    current_file=r["current_file"],
                    agent_client=r["agent_client"],
                    last_heartbeat=datetime.fromisoformat(r["last_heartbeat"]),
                    source=r["source"],
                    is_online=bool(r["is_online"]) and (datetime.utcnow() - datetime.fromisoformat(r["last_heartbeat"]).replace(tzinfo=None)).total_seconds() < 120,
                )
            )
        return res

    @atomic(write=True)
    def bind_worktree_task(self, worktree_id: str, task_id: Optional[str]) -> bool:
        wt = self.conn.execute("SELECT * FROM worktree_instances WHERE id=?", (worktree_id,)).fetchone()
        if wt is None:
            return False
        self.validate_scope(wt['project_id'], task_id, require_active=True)
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE worktree_instances SET active_task_id = ? WHERE id = ?",
            (task_id, worktree_id),
        )
        return cur.rowcount > 0

    # --- Telemetry Events ---

    @atomic(write=True)
    def log_telemetry_event(self, project_id: str, event_type: str, summary: str, details: Optional[Dict[str, Any]] = None):
        cur = self.conn.cursor()
        eid = f"evt_{uuid.uuid4().hex}"
        cur.execute(
            """INSERT INTO telemetry_events (id, project_id, event_type, summary, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                eid,
                project_id,
                event_type,
                summary,
                json.dumps(details or {}),
                datetime.utcnow().isoformat(),
            ),
        )

    @atomic(write=False)
    def list_telemetry_events(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM telemetry_events WHERE source != 'demo' AND project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        res = []
        for r in cur.fetchall():
            res.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "event_type": r["event_type"],
                "summary": r["summary"],
                "details": json.loads(r["details"]) if r["details"] else {},
                "created_at": r["created_at"],
            })
        return res

    # --- Intelligent Health Check & Conflict Detection Engine ---

    @atomic(write=False)
    def check_project_health(self, project_id: str) -> HealthCheckReport:
        rules = self.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        tasks = self.list_tasks(project_id)
        task_ids = {t.id: t.status for t in tasks}

        conflicts: List[RuleConflict] = []
        fatigued_rules: List[Rule] = []
        noisy_rules: List[Rule] = []

        penalty = 0

        # 1. Detect Overlapping Scope Conflicts & Contradictions
        for i in range(len(rules)):
            r1 = rules[i]
            if r1.zero_score_count >= 2:
                fatigued_rules.append(r1)
            if r1.one_score_count >= 2:
                noisy_rules.append(r1)
                penalty += 4

            # Orphan Task check
            if r1.task_id and (r1.task_id not in task_ids or task_ids[r1.task_id] == TaskStatus.ARCHIVED):
                conflicts.append(
                    RuleConflict(
                        id=f"conf_orphan_{r1.id}",
                        conflict_type="orphan_task",
                        severity="warning",
                        title=f"孤儿规则: 所属任务已归档 ({r1.title})",
                        description=f"规则 {r1.id} 绑定任务 {r1.task_id}，但该任务已被归档或不存在，规则仍在下发短期约束。",
                        involved_rule_ids=[r1.id],
                        suggested_fix="建议将有价值的条款结晶升华为长期骨骼，或归档废弃该规则。",
                    )
                )
                penalty += 5

            for j in range(i + 1, len(rules)):
                r2 = rules[j]
                # Check scope overlap
                set1 = set(r1.scope_patterns)
                set2 = set(r2.scope_patterns)
                if set1.intersection(set2):
                    # Check priority inversion: same scopes with different priorities
                    if r1.priority != r2.priority and r1.lifecycle == r2.lifecycle:
                        conflicts.append(
                            RuleConflict(
                                id=f"conf_prio_{r1.id}_{r2.id}",
                                conflict_type="scope_overlap",
                                severity="info",
                                title=f"同作用域需人工核对: {r1.title} ({r1.priority.value}) vs {r2.title} ({r2.priority.value})",
                                description=f"两条规则作用于相同范围 {', '.join(set1.intersection(set2))}；范围或优先级本身不能证明语义冲突。",
                                involved_rule_ids=[r1.id, r2.id],
                                suggested_fix="核对规则职责，建议将核心约束提升为一致的优先级定级。",
                            )
                        )

        score = max(0, 100 - penalty)
        status_label = "needs_review" if conflicts or noisy_rules else "no_structural_findings"

        return HealthCheckReport(
            project_id=project_id,
            overall_score=score,
            status_label=status_label,
            total_rules=len(rules),
            conflicts=conflicts,
            fatigued_rules=fatigued_rules,
            noisy_rules=noisy_rules,
            checked_at=datetime.utcnow(),
        )

    # --- Rule Evaluation Operations (Debug Mode) ---

    @atomic(write=True)
    def record_evaluation(self, eval_item: RuleEvaluation) -> RuleEvaluation:
        rule = self.get_rule(eval_item.rule_id)
        if rule is None or rule.project_id != eval_item.project_id:
            raise DomainError("Evaluation rule does not belong to this project.")
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO rule_evaluations (id, project_id, rule_id, score, file_path, reason, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eval_item.id,
                eval_item.project_id,
                eval_item.rule_id,
                eval_item.score,
                eval_item.file_path,
                eval_item.reason,
                eval_item.session_id,
                eval_item.created_at.isoformat(),
            ),
        )

        self.conn.execute("UPDATE rule_evaluations SET source=? WHERE id=?", (eval_item.source, eval_item.id))
        self.conn.execute("UPDATE rule_evaluations SET delivery_id=?,rule_version=? WHERE id=?", (eval_item.delivery_id, eval_item.rule_version, eval_item.id))

        cur.execute(
            """SELECT AVG(score), COUNT(*),
                      SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END)
               FROM rule_evaluations WHERE rule_id = ? AND source = 'agent' AND rule_version = (SELECT version FROM rules WHERE id=?)""",
            (eval_item.rule_id, eval_item.rule_id),
        )
        row = cur.fetchone()
        avg_score = row[0]
        total_evals = row[1]
        zeros = row[2]
        ones = row[3]

        cur.execute(
            """UPDATE rules SET avg_score = ?, eval_count = ?, zero_score_count = ?, one_score_count = ?, updated_at = ?
               WHERE id = ?""",
            (
                round(avg_score, 2) if avg_score is not None else None,
                total_evals or 0,
                zeros or 0,
                ones or 0,
                datetime.utcnow().isoformat(),
                eval_item.rule_id,
            ),
        )
        return eval_item

    @atomic(write=False)
    def list_evaluations(
        self, project_id: str, rule_id: Optional[str] = None, limit: int = 100
    ) -> List[RuleEvaluation]:
        query = "SELECT * FROM rule_evaluations WHERE source != 'demo' AND project_id = ?"
        params: List[Any] = [project_id]
        if rule_id:
            query += " AND rule_id = ?"
            params.append(rule_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur = self.conn.cursor()
        cur.execute(query, params)
        res = []
        for row in cur.fetchall():
            res.append(
                RuleEvaluation(
                    id=row["id"],
                    project_id=row["project_id"],
                    rule_id=row["rule_id"],
                    score=row["score"],
                    source=row["source"], delivery_id=row["delivery_id"], rule_version=row["rule_version"],
                    file_path=row["file_path"],
                    reason=row["reason"],
                    session_id=row["session_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    # --- Agent Issue Operations (Debug Mode) ---

    @atomic(write=True)
    def record_issue(self, issue: AgentIssue) -> AgentIssue:
        self.validate_scope(issue.project_id)
        for rule_id in issue.related_rule_ids:
            rule = self.get_rule(rule_id)
            if rule is None or rule.project_id != issue.project_id:
                raise DomainError("Issue references a rule from another project.")
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO agent_issues (id, project_id, issue_type, title, description,
                                        file_path, related_rule_ids, suggested_action,
                                        status, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue.id,
                issue.project_id,
                issue.issue_type.value,
                issue.title,
                issue.description,
                issue.file_path,
                json.dumps(issue.related_rule_ids),
                issue.suggested_action,
                issue.status.value,
                issue.created_at.isoformat(),
                issue.resolved_at.isoformat() if issue.resolved_at else None,
            ),
        )
        self.conn.execute("UPDATE agent_issues SET source=? WHERE id=?", (issue.source, issue.id))
        self.conn.execute("UPDATE agent_issues SET session_id=? WHERE id=?", (issue.session_id, issue.id))
        return issue

    @atomic(write=False)
    def list_issues(
        self, project_id: str, status: Optional[IssueStatus] = None
    ) -> List[AgentIssue]:
        query = "SELECT * FROM agent_issues WHERE source != 'demo' AND project_id = ?"
        params: List[Any] = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"

        cur = self.conn.cursor()
        cur.execute(query, params)
        res = []
        for row in cur.fetchall():
            res.append(
                AgentIssue(
                    id=row["id"],
                    project_id=row["project_id"],
                    issue_type=IssueType(row["issue_type"]),
                    source=row["source"], session_id=row["session_id"],
                    title=row["title"],
                    description=row["description"],
                    file_path=row["file_path"],
                    related_rule_ids=json.loads(row["related_rule_ids"]),
                    suggested_action=row["suggested_action"],
                    status=IssueStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    resolved_at=(
                        datetime.fromisoformat(row["resolved_at"])
                        if row["resolved_at"]
                        else None
                    ),
                )
            )
        return res

    @atomic(write=True)
    def resolve_issue(self, issue_id: str, status: IssueStatus = IssueStatus.RESOLVED) -> bool:
        cur = self.conn.cursor()
        now_str = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE agent_issues SET status = ?, resolved_at = ? WHERE id = ?",
            (status.value, now_str, issue_id),
        )
        return cur.rowcount > 0

    # --- Finding Operations ---

    @atomic(write=True)
    def create_finding(self, finding: Finding) -> Finding:
        self.validate_scope(finding.project_id, finding.task_id)
        finding.target_path = relative_path(finding.target_path, pattern=True)
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO findings (id, project_id, task_id, session_id, target_path,
                                     finding_text, suggested_priority, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding.id,
                finding.project_id,
                finding.task_id,
                finding.session_id,
                finding.target_path,
                finding.finding_text,
                finding.suggested_priority.value,
                finding.status.value,
                finding.created_at.isoformat(),
            ),
        )
        self.conn.execute("UPDATE findings SET source=? WHERE id=?", (finding.source, finding.id))
        return finding

    @atomic(write=False)
    def list_findings(
        self, project_id: str, status: Optional[FindingStatus] = None
    ) -> List[Finding]:
        query = "SELECT * FROM findings WHERE source != 'demo' AND project_id = ?"
        params: List[Any] = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"

        cur = self.conn.cursor()
        cur.execute(query, params)
        res = []
        for row in cur.fetchall():
            res.append(
                Finding(
                    id=row["id"],
                    project_id=row["project_id"],
                    task_id=row["task_id"],
                    session_id=row["session_id"],
                    target_path=row["target_path"],
                    finding_text=row["finding_text"],
                    source=row["source"],
                    suggested_priority=Priority(row["suggested_priority"]),
                    status=FindingStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    @atomic(write=True)
    def update_finding_status(self, finding_id: str, status: FindingStatus) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE findings SET status = ? WHERE id = ?",
            (status.value, finding_id),
        )
        return cur.rowcount > 0

    # --- Proposal Operations ---

    @atomic(write=True)
    def create_proposal(self, proposal: Proposal) -> Proposal:
        self.validate_scope(proposal.project_id, proposal.task_id)
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO proposals (id, project_id, task_id, target_component,
                                      proposed_contract, justification, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id,
                proposal.project_id,
                proposal.task_id,
                proposal.target_component,
                proposal.proposed_contract,
                proposal.justification,
                proposal.status,
                proposal.created_at.isoformat(),
            ),
        )
        return proposal

    @atomic(write=False)
    def list_proposals(self, project_id: str, status: Optional[str] = None) -> List[Proposal]:
        query = "SELECT * FROM proposals WHERE project_id = ?"
        params: List[Any] = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        cur = self.conn.cursor()
        cur.execute(query, params)
        res = []
        for row in cur.fetchall():
            res.append(
                Proposal(
                    id=row["id"],
                    project_id=row["project_id"],
                    task_id=row["task_id"],
                    target_component=row["target_component"],
                    proposed_contract=row["proposed_contract"],
                    justification=row["justification"],
                    status=row["status"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    def _row_to_rule(self, row: sqlite3.Row) -> Rule:
        row_keys = row.keys()
        return Rule(
            id=row["id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            scope_patterns=json.loads(row["scope_patterns"]),
            priority=Priority(row["priority"]),
            lifecycle=Lifecycle(row["lifecycle"]),
            title=row["title"],
            content_points=json.loads(row["content_points"]),
            created_by=row["created_by"],
            status=RuleStatus(row["status"]),
            version=row["version"] if "version" in row_keys and row["version"] else 1,
            hit_count=row["hit_count"],
            legacy_hit_count=row["legacy_hit_count"],
            last_hit_at=(
                datetime.fromisoformat(row["last_hit_at"])
                if row["last_hit_at"]
                else None
            ),
            avg_score=row["avg_score"] if "avg_score" in row_keys else None,
            eval_count=row["eval_count"] if "eval_count" in row_keys else 0,
            zero_score_count=row["zero_score_count"] if "zero_score_count" in row_keys else 0,
            one_score_count=row["one_score_count"] if "one_score_count" in row_keys else 0,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @atomic(write=False)
    def validate_scope(self, project_id: str, task_id: Optional[str] = None, require_active: bool = False):
        if self.get_project(project_id) is None:
            raise DomainError("Project not found.", "not_found", 404)
        if task_id:
            task = self.get_task(task_id)
            if task is None or task.project_id != project_id:
                raise DomainError("Task does not belong to this project.")
            if require_active and task.status not in (TaskStatus.ACTIVE, TaskStatus.TESTING):
                raise Conflict("Task is not active; its short-term rules cannot be activated.")

    @atomic(write=True)
    def audit(self, project_id, actor, action, entity_id, details):
        self.conn.execute("INSERT INTO audit_events(project_id,actor,action,entity_id,details,created_at) VALUES(?,?,?,?,?,?)", (project_id, actor, action, entity_id, json.dumps(details, ensure_ascii=False), datetime.utcnow().isoformat()))

    @atomic(write=True)
    def delete_rule(self, rule_id, expected_version=None):
        # Preserve deliveries, feedback and version history for an auditable deletion.
        return self.update_rule_status(rule_id, RuleStatus.REVOKED, expected_version)
