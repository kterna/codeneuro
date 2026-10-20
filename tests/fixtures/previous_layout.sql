-- Synthetic migration fixture: table definitions only, no local business data.
CREATE TABLE agent_rule_state (
	rule_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	evidence_version INTEGER NOT NULL,
	half_life_days INTEGER NOT NULL,
	revision_at VARCHAR(40) NOT NULL,
	PRIMARY KEY (rule_id),
	FOREIGN KEY(rule_id) REFERENCES rules (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE audit (
	sequence INTEGER NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	actor VARCHAR(128) NOT NULL,
	action VARCHAR(100) NOT NULL,
	entity_id VARCHAR(128) NOT NULL,
	details_json TEXT NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	PRIMARY KEY (sequence),
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE "contract_proposals" (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	target_rule_id VARCHAR(128) NOT NULL,
	target_version INTEGER NOT NULL,
	title VARCHAR(500) NOT NULL,
	points_json TEXT NOT NULL,
	patterns_json TEXT NOT NULL,
	priority VARCHAR(2) NOT NULL,
	category VARCHAR(16),
	reason TEXT NOT NULL,
	status VARCHAR(16) NOT NULL,
	decision_reason TEXT,
	reviewer_id VARCHAR(128),
	topics_json TEXT DEFAULT '[]' NOT NULL,
	is_global BOOLEAN DEFAULT '0' NOT NULL,
	priority_reason TEXT DEFAULT '' NOT NULL,
	validation_spec_json TEXT,
	schema_version INTEGER DEFAULT '2' NOT NULL,
	source_rule_id VARCHAR(128),
	source_version INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT ck_contract_proposals_retained_0 CHECK (status IN ('pending','approved','rejected')),
	CONSTRAINT fk_proposal_candidate_version FOREIGN KEY(source_rule_id, source_version) REFERENCES rule_versions (rule_id, version),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(task_id) REFERENCES tasks (id),
	FOREIGN KEY(target_rule_id) REFERENCES rules (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE deliveries (
	id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	request_id VARCHAR(128) NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	response_json TEXT NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id),
	CONSTRAINT uq_delivery_request UNIQUE (session_id, request_id)
);

CREATE TABLE delivery_findings (
	delivery_id VARCHAR(128) NOT NULL,
	finding_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (delivery_id, finding_id),
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id),
	FOREIGN KEY(finding_id) REFERENCES findings (id)
);

CREATE TABLE delivery_requirements (
	delivery_id VARCHAR(128) NOT NULL,
	requirement_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	PRIMARY KEY (delivery_id, requirement_id),
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id),
	FOREIGN KEY(requirement_id, version) REFERENCES requirement_versions (requirement_id, version)
);

CREATE TABLE delivery_rules (
	delivery_id VARCHAR(128) NOT NULL,
	rule_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	representation VARCHAR(16) NOT NULL,
	PRIMARY KEY (delivery_id, rule_id),
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id),
	FOREIGN KEY(rule_id, version) REFERENCES rule_versions (rule_id, version)
);

CREATE TABLE feedback (
	delivery_id VARCHAR(128) NOT NULL,
	rule_id VARCHAR(128) NOT NULL,
	rule_version INTEGER NOT NULL,
	score INTEGER NOT NULL,
	reason TEXT NOT NULL,
	PRIMARY KEY (delivery_id, rule_id),
	CHECK (score >= 0 AND score <= 5),
	FOREIGN KEY(delivery_id, rule_id) REFERENCES delivery_rules (delivery_id, rule_id)
);

CREATE TABLE finding_topics (
	project_id VARCHAR(128) NOT NULL,
	finding_id VARCHAR(128) NOT NULL,
	topic_key VARCHAR(64) NOT NULL,
	PRIMARY KEY (finding_id, topic_key),
	FOREIGN KEY(finding_id, project_id) REFERENCES findings (id, project_id),
	FOREIGN KEY(project_id, topic_key) REFERENCES project_topics (project_id, "key")
);

CREATE TABLE "findings" (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	target_path TEXT,
	text TEXT NOT NULL,
	priority VARCHAR(2) NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_findings_project UNIQUE (id, project_id),
	CONSTRAINT ck_findings_priority CHECK (priority IN ('P0','P1','P2','P3')),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id),
	FOREIGN KEY(task_id) REFERENCES tasks (id)
);

CREATE TABLE issues (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	issue_type VARCHAR(32) NOT NULL,
	title VARCHAR(500) NOT NULL,
	description TEXT NOT NULL,
	file_path TEXT NOT NULL,
	related_rules_json TEXT NOT NULL,
	suggested_action TEXT NOT NULL,
	status VARCHAR(20) DEFAULT 'open' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE project_topics (
	project_id VARCHAR(128) NOT NULL,
	"key" VARCHAR(64) NOT NULL,
	name VARCHAR(200) NOT NULL,
	description TEXT NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	definition_locked BOOLEAN DEFAULT '0' NOT NULL,
	PRIMARY KEY (project_id, "key"),
	CONSTRAINT ck_topics_status CHECK (status IN ('active','deleted')),
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE projects (
	id VARCHAR(128) NOT NULL,
	name VARCHAR(500) NOT NULL,
	rule_revision INTEGER DEFAULT '0' NOT NULL, taxonomy_revision INTEGER DEFAULT '0' NOT NULL, topic_query_enabled BOOLEAN DEFAULT '0' NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE requirement_rule_links (
	rule_id VARCHAR(128) NOT NULL,
	requirement_id VARCHAR(128) NOT NULL,
	PRIMARY KEY (rule_id),
	FOREIGN KEY(requirement_id) REFERENCES requirements (id),
	FOREIGN KEY(rule_id) REFERENCES rules (id)
);

CREATE TABLE requirement_versions (
	requirement_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	original_text TEXT NOT NULL,
	status VARCHAR(16) NOT NULL,
	completion_summary TEXT,
	PRIMARY KEY (requirement_id, version),
	FOREIGN KEY(requirement_id) REFERENCES requirements (id)
);

CREATE TABLE "requirements" (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128),
	request_id VARCHAR(128),
	web_request_id VARCHAR(128),
	original_text TEXT NOT NULL,
	status VARCHAR(16) NOT NULL,
	version INTEGER NOT NULL,
	completion_summary TEXT,
	current_text TEXT DEFAULT '' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_requirement_submission UNIQUE (session_id, request_id),
	CONSTRAINT uq_web_requirement_intake UNIQUE (project_id, web_request_id),
	CONSTRAINT ck_requirements_status CHECK (status IN ('active','archived','deleted')),
	FOREIGN KEY(task_id) REFERENCES tasks (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE rule_observations (
	id VARCHAR(128) NOT NULL,
	rule_id VARCHAR(128) NOT NULL,
	evidence_version INTEGER NOT NULL,
	test_report_id VARCHAR(128) NOT NULL,
	supports BOOLEAN NOT NULL,
	reason TEXT NOT NULL,
	created_at VARCHAR(40) NOT NULL, check_ids_json TEXT DEFAULT '[]' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(rule_id) REFERENCES rules (id),
	FOREIGN KEY(test_report_id) REFERENCES test_reports (id),
	CONSTRAINT uq_rule_evidence UNIQUE (rule_id, evidence_version, test_report_id)
);

CREATE TABLE rule_reviews (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	rule_id VARCHAR(128) NOT NULL,
	rule_version INTEGER NOT NULL,
	approve BOOLEAN NOT NULL,
	reason TEXT NOT NULL,
	reviewer_id VARCHAR(128) NOT NULL,
	created_at VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(rule_id, rule_version) REFERENCES rule_versions (rule_id, version),
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE rule_topics (
	project_id VARCHAR(128) NOT NULL,
	rule_id VARCHAR(128) NOT NULL,
	topic_key VARCHAR(64) NOT NULL,
	PRIMARY KEY (rule_id, topic_key),
	FOREIGN KEY(rule_id, project_id) REFERENCES rules (id, project_id),
	FOREIGN KEY(project_id, topic_key) REFERENCES project_topics (project_id, "key")
);

CREATE TABLE "rule_versions" (
	rule_id VARCHAR(128) NOT NULL,
	version INTEGER NOT NULL,
	title VARCHAR(500) NOT NULL,
	points_json TEXT NOT NULL,
	patterns_json TEXT NOT NULL,
	priority VARCHAR(2) NOT NULL,
	category VARCHAR(16),
	status VARCHAR(16) NOT NULL,
	topics_json TEXT DEFAULT '[]' NOT NULL,
	is_global BOOLEAN DEFAULT '0' NOT NULL,
	priority_reason TEXT DEFAULT '' NOT NULL,
	validation_spec_json TEXT,
	schema_version INTEGER DEFAULT '2' NOT NULL,
	PRIMARY KEY (rule_id, version),
	FOREIGN KEY(rule_id) REFERENCES rules (id)
);

CREATE TABLE "rules" (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128),
	title VARCHAR(500) NOT NULL,
	points_json TEXT NOT NULL,
	patterns_json TEXT NOT NULL,
	priority VARCHAR(2) NOT NULL,
	status VARCHAR(16) NOT NULL,
	version INTEGER NOT NULL,
	origin_rule_id VARCHAR(128),
	origin_version INTEGER,
	origin_reason TEXT,
	is_global BOOLEAN DEFAULT '0' NOT NULL,
	priority_reason TEXT DEFAULT '' NOT NULL,
	validation_spec_json TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_promotion_source_version UNIQUE (origin_rule_id, origin_version),
	CONSTRAINT ck_rules_retained_2 CHECK (status IN ('draft','active','deprecated','revoked')),
	CONSTRAINT ck_rules_priority CHECK (priority IN ('P0','P1','P2','P3')),
	CONSTRAINT uq_rules_project UNIQUE (id, project_id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(origin_rule_id) REFERENCES rules (id),
	FOREIGN KEY(task_id) REFERENCES tasks (id)
);

CREATE TABLE sessions (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128),
	worktree_id VARCHAR(128) NOT NULL,
	workspace TEXT NOT NULL,
	agent_client VARCHAR(128) NOT NULL,
	actor_id VARCHAR(128) NOT NULL,
	debug BOOLEAN NOT NULL,
	state VARCHAR(16) NOT NULL,
	knowledge_revision INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CHECK (state IN ('active','closed')),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(task_id) REFERENCES tasks (id),
	FOREIGN KEY(worktree_id) REFERENCES worktrees (id)
);

CREATE TABLE "tasks" (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	title VARCHAR(500) NOT NULL,
	description TEXT DEFAULT '' NOT NULL,
	status VARCHAR(16) NOT NULL,
	revision INTEGER DEFAULT '0' NOT NULL,
	paused_from VARCHAR(16),
	PRIMARY KEY (id),
	CONSTRAINT ck_tasks_retained_1 CHECK (paused_from IS NULL OR paused_from IN ('active','testing')),
	CONSTRAINT ck_tasks_status CHECK (status IN ('draft','active','testing','paused','released','archived','deleted')),
	FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE test_reports (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	task_id VARCHAR(128) NOT NULL,
	session_id VARCHAR(128) NOT NULL,
	request_id VARCHAR(128) NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	command_json TEXT NOT NULL,
	paths_json TEXT NOT NULL,
	exit_code INTEGER NOT NULL,
	started_at VARCHAR(40) NOT NULL,
	finished_at VARCHAR(40) NOT NULL,
	recorded_at VARCHAR(40) NOT NULL,
	source VARCHAR(24) NOT NULL, test_cases_json TEXT DEFAULT '[]' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(session_id) REFERENCES sessions (id),
	FOREIGN KEY(task_id) REFERENCES tasks (id),
	CONSTRAINT uq_test_unique_event UNIQUE (session_id, fingerprint),
	CONSTRAINT uq_test_request UNIQUE (session_id, request_id)
);

CREATE TABLE worktrees (
	id VARCHAR(128) NOT NULL,
	project_id VARCHAR(128) NOT NULL,
	actor_id VARCHAR(128) NOT NULL,
	workspace TEXT NOT NULL,
	machine_name VARCHAR(255) NOT NULL,
	platform VARCHAR(16) NOT NULL,
	repo_identity VARCHAR(128),
	git_branch VARCHAR(255) DEFAULT '' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id)
);
