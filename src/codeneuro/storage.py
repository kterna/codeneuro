"""SQLite storage implementation with WAL mode and robust schema initialization."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from codeneuro.models import (
    AgentIssue,
    Finding,
    FindingStatus,
    IssueStatus,
    IssueType,
    Lifecycle,
    Priority,
    Project,
    Proposal,
    Rule,
    RuleEvaluation,
    RuleStatus,
    Task,
    TaskStatus,
)


class Storage:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row
        self._init_db()

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
            hit_count INTEGER DEFAULT 0,
            last_hit_at TEXT,
            avg_score REAL,
            eval_count INTEGER DEFAULT 0,
            zero_score_count INTEGER DEFAULT 0,
            one_score_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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

        CREATE INDEX IF NOT EXISTS idx_rules_project ON rules(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_rules_task ON rules(task_id);
        CREATE INDEX IF NOT EXISTS idx_findings_project ON findings(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_evals_rule ON rule_evaluations(rule_id);
        CREATE INDEX IF NOT EXISTS idx_issues_project ON agent_issues(project_id, status);
        """)

        # Migration columns if rules table existed previously
        for col_def in [
            ("avg_score", "REAL"),
            ("eval_count", "INTEGER DEFAULT 0"),
            ("zero_score_count", "INTEGER DEFAULT 0"),
            ("one_score_count", "INTEGER DEFAULT 0")
        ]:
            try:
                cur.execute(f"ALTER TABLE rules ADD COLUMN {col_def[0]} {col_def[1]}")
            except sqlite3.OperationalError:
                pass

    # --- Project Operations ---

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

    def create_task(self, task: Task) -> Task:
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

    def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, datetime.utcnow().isoformat(), task_id),
        )
        return cur.rowcount > 0

    # --- Rule Operations ---

    def create_rule(self, rule: Rule) -> Rule:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO rules (id, project_id, task_id, scope_patterns, priority,
                                  lifecycle, title, content_points, created_by, status,
                                  hit_count, last_hit_at, avg_score, eval_count,
                                  zero_score_count, one_score_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                rule.hit_count,
                rule.last_hit_at.isoformat() if rule.last_hit_at else None,
                rule.avg_score,
                rule.eval_count,
                rule.zero_score_count,
                rule.one_score_count,
                rule.created_at.isoformat(),
                rule.updated_at.isoformat(),
            ),
        )
        return rule

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_rule(row)

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

    def update_rule_status(self, rule_id: str, status: RuleStatus) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE rules SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, datetime.utcnow().isoformat(), rule_id),
        )
        return cur.rowcount > 0

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

    # --- Rule Evaluation Operations (Debug Mode) ---

    def record_evaluation(self, eval_item: RuleEvaluation) -> RuleEvaluation:
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

        # Update aggregated stats on the rule
        cur.execute(
            """SELECT AVG(score), COUNT(*),
                      SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END),
                      SUM(CASE WHEN score = 1 THEN 1 ELSE 0 END)
               FROM rule_evaluations WHERE rule_id = ?""",
            (eval_item.rule_id,),
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

    def list_evaluations(
        self, project_id: str, rule_id: Optional[str] = None, limit: int = 100
    ) -> List[RuleEvaluation]:
        query = "SELECT * FROM rule_evaluations WHERE project_id = ?"
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
                    file_path=row["file_path"],
                    reason=row["reason"],
                    session_id=row["session_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    # --- Agent Issue Operations (Debug Mode) ---

    def record_issue(self, issue: AgentIssue) -> AgentIssue:
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
        return issue

    def list_issues(
        self, project_id: str, status: Optional[IssueStatus] = None
    ) -> List[AgentIssue]:
        query = "SELECT * FROM agent_issues WHERE project_id = ?"
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

    def resolve_issue(self, issue_id: str, status: IssueStatus = IssueStatus.RESOLVED) -> bool:
        cur = self.conn.cursor()
        now_str = datetime.utcnow().isoformat()
        cur.execute(
            "UPDATE agent_issues SET status = ?, resolved_at = ? WHERE id = ?",
            (status.value, now_str, issue_id),
        )
        return cur.rowcount > 0

    # --- Finding Operations ---

    def create_finding(self, finding: Finding) -> Finding:
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
        return finding

    def list_findings(
        self, project_id: str, status: Optional[FindingStatus] = None
    ) -> List[Finding]:
        query = "SELECT * FROM findings WHERE project_id = ?"
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
                    suggested_priority=Priority(row["suggested_priority"]),
                    status=FindingStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return res

    def update_finding_status(self, finding_id: str, status: FindingStatus) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE findings SET status = ? WHERE id = ?",
            (status.value, finding_id),
        )
        return cur.rowcount > 0

    # --- Proposal Operations ---

    def create_proposal(self, proposal: Proposal) -> Proposal:
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
            hit_count=row["hit_count"],
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
