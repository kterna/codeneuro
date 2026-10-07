-- Historical schema shipped before the reliability migration. No user records.
CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            root_paths TEXT NOT NULL, -- JSON list
            created_at TEXT NOT NULL
        );

CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

CREATE TABLE rules (
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        , avg_score REAL, eval_count INTEGER DEFAULT 0, zero_score_count INTEGER DEFAULT 0, one_score_count INTEGER DEFAULT 0, version INTEGER DEFAULT 1);

CREATE TABLE findings (
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

CREATE TABLE proposals (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            target_component TEXT NOT NULL,
            proposed_contract TEXT NOT NULL,
            justification TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

CREATE TABLE rule_evaluations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            score INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            reason TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL
        );

CREATE TABLE agent_issues (
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

CREATE TABLE rule_versions (
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

CREATE TABLE worktree_instances (
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

CREATE TABLE telemetry_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL, -- jit_hit | finding | issue | rule_edit | heartbeat
            summary TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
