"""Additive, transactional migrations. Legacy evidence is preserved and labelled."""
from .database import DomainError

SCHEMA_VERSION = 1


def migrate(store):
    with store.transaction():
        conn = store.conn
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise DomainError("Database schema is newer than this CodeNeuro version.")
        if version == SCHEMA_VERSION:
            return
        additions = {
            "rules": {"legacy_hit_count": "INTEGER NOT NULL DEFAULT 0"},
            "rule_versions": {"status": "TEXT NOT NULL DEFAULT 'active'", "task_id": "TEXT"},
            "findings": {"source": "TEXT NOT NULL DEFAULT 'human'"},
            "agent_issues": {"source": "TEXT NOT NULL DEFAULT 'human'", "session_id": "TEXT"},
            "rule_evaluations": {"source": "TEXT NOT NULL DEFAULT 'human'", "delivery_id": "TEXT", "rule_version": "INTEGER"},
            "worktree_instances": {"source": "TEXT NOT NULL DEFAULT 'client'"},
            "telemetry_events": {"source": "TEXT NOT NULL DEFAULT 'system'"},
        }
        for table, columns in additions.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, declaration in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_rule_version ON rule_versions(rule_id, version_number)")
        conn.execute("""CREATE TABLE agent_sessions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            worktree_id TEXT NOT NULL REFERENCES worktree_instances(id), task_id TEXT REFERENCES tasks(id),
            agent_client TEXT NOT NULL, debug INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE context_deliveries (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES agent_sessions(id),
            request_id TEXT NOT NULL, file_path TEXT NOT NULL, request_json TEXT NOT NULL,
            response_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(session_id, request_id))""")
        conn.execute("""CREATE TABLE delivery_rules (
            delivery_id TEXT NOT NULL REFERENCES context_deliveries(id), rule_id TEXT NOT NULL,
            rule_version INTEGER NOT NULL, representation TEXT NOT NULL,
            PRIMARY KEY(delivery_id, rule_id))""")
        conn.execute("""CREATE TABLE session_knowledge (
            session_id TEXT NOT NULL REFERENCES agent_sessions(id), rule_id TEXT NOT NULL,
            rule_version INTEGER NOT NULL, acknowledged_at TEXT NOT NULL,
            PRIMARY KEY(session_id, rule_id, rule_version))""")
        conn.execute("""CREATE TABLE audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT,
            actor TEXT NOT NULL, action TEXT NOT NULL, entity_id TEXT NOT NULL,
            details TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX ix_deliveries_session ON context_deliveries(session_id, created_at)")
        conn.execute("CREATE INDEX ix_audit_project ON audit_events(project_id, sequence)")
        conn.execute("CREATE UNIQUE INDEX ux_feedback_receipt ON rule_evaluations(delivery_id, rule_id) WHERE delivery_id IS NOT NULL")
        # Old hits included manual previews and fabricated pings. Do not represent
        # them as delivered agent context. Preserve the old number explicitly.
        conn.execute("UPDATE rules SET legacy_hit_count=hit_count, hit_count=0, last_hit_at=NULL")
        for table in ["findings", "rule_evaluations", "agent_issues", "worktree_instances", "telemetry_events"]:
            conn.execute(f"UPDATE {table} SET source='legacy'")
        conn.execute("UPDATE findings SET source='demo' WHERE id GLOB 'find_live_*' OR id GLOB 'find_loop_*'")
        conn.execute("UPDATE rule_evaluations SET source='demo' WHERE id IN ('eval_001','eval_002') AND session_id='sess_codex_01'")
        conn.execute("UPDATE agent_issues SET source='demo' WHERE id='issue_001' AND title LIKE 'RCON 批量执行超时%'")
        conn.execute("UPDATE worktree_instances SET source='demo', is_online=0 WHERE id='wt_local_main' AND agent_client='Codex CLI (PTY)'")
        conn.execute("UPDATE rules SET avg_score=NULL,eval_count=0,zero_score_count=0,one_score_count=0")
        conn.execute("UPDATE rule_versions SET task_id=(SELECT task_id FROM rules WHERE rules.id=rule_versions.rule_id)")
        conn.execute("""INSERT INTO rule_versions(id,rule_id,project_id,version_number,title,scope_patterns,priority,lifecycle,content_points,change_summary,created_by,created_at,status,task_id)
            SELECT 'ver_migration_'||r.id,r.id,r.project_id,r.version,r.title,r.scope_patterns,r.priority,r.lifecycle,r.content_points,
                   'Imported current legacy version',r.created_by,r.updated_at,r.status,r.task_id
            FROM rules r WHERE NOT EXISTS(SELECT 1 FROM rule_versions v WHERE v.rule_id=r.id AND v.version_number=r.version)""")
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
