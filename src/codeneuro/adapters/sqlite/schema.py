"""One relational model. Alembic owns schema changes; startup never migrates."""
import sqlalchemy as sa

metadata = sa.MetaData()
CURRENT_SCHEMA = '3d5f9b7c012e'

projects = sa.Table('projects', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('name', sa.String(500), nullable=False),
    sa.Column('rule_revision', sa.Integer, nullable=False, server_default='0'),
    sa.Column('taxonomy_revision', sa.Integer, nullable=False, server_default='0'),
    sa.Column('topic_query_enabled', sa.Boolean, nullable=False, server_default='0'))

project_topics = sa.Table('project_topics', metadata,
    sa.Column('project_id', sa.ForeignKey('projects.id'), primary_key=True),
    sa.Column('key', sa.String(64), primary_key=True),
    sa.Column('name', sa.String(200), nullable=False),
    sa.Column('description', sa.Text, nullable=False),
    sa.Column('version', sa.Integer, nullable=False),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('definition_locked', sa.Boolean, nullable=False, server_default='0'),
    sa.CheckConstraint("status IN ('active','deleted')", name='ck_topics_status'))

rule_topics = sa.Table('rule_topics', metadata,
    sa.Column('project_id', sa.String(128), nullable=False),
    sa.Column('rule_id', sa.String(128), primary_key=True),
    sa.Column('topic_key', sa.String(64), primary_key=True),
    sa.ForeignKeyConstraint(['rule_id', 'project_id'], ['rules.id', 'rules.project_id']),
    sa.ForeignKeyConstraint(['project_id', 'topic_key'], ['project_topics.project_id', 'project_topics.key']),
    sa.Index('ix_rule_topics_lookup', 'project_id', 'topic_key'))

finding_topics = sa.Table('finding_topics', metadata,
    sa.Column('project_id', sa.String(128), nullable=False),
    sa.Column('finding_id', sa.String(128), primary_key=True),
    sa.Column('topic_key', sa.String(64), primary_key=True),
    sa.ForeignKeyConstraint(['finding_id', 'project_id'], ['findings.id', 'findings.project_id']),
    sa.ForeignKeyConstraint(['project_id', 'topic_key'], ['project_topics.project_id', 'project_topics.key']),
    sa.Index('ix_finding_topics_lookup', 'project_id', 'topic_key'))

tasks = sa.Table('tasks', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False, index=True),
    sa.Column('title', sa.String(500), nullable=False),
    sa.Column('description', sa.Text, nullable=False, server_default=''),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('revision', sa.Integer, nullable=False, server_default='0'),
    sa.Column('paused_from', sa.String(16)),
    sa.CheckConstraint("status IN ('draft','active','testing','paused','released','archived','deleted')", name='ck_tasks_status'),
    sa.CheckConstraint("paused_from IS NULL OR paused_from IN ('active','testing')"))

worktrees = sa.Table('worktrees', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('actor_id', sa.String(128), nullable=False),
    sa.Column('workspace', sa.Text, nullable=False),
    sa.Column('machine_name', sa.String(255), nullable=False),
    sa.Column('platform', sa.String(16), nullable=False),
    sa.Column('repo_identity', sa.String(128)),
    sa.Column('git_branch', sa.String(255), nullable=False, server_default=''),
    sa.Index('ix_worktree_scope', 'project_id', 'actor_id'))

sessions = sa.Table('sessions', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False, index=True),
    sa.Column('task_id', sa.ForeignKey('tasks.id'), nullable=True),
    sa.Column('worktree_id', sa.ForeignKey('worktrees.id'), nullable=False),
    sa.Column('workspace', sa.Text, nullable=False),
    sa.Column('agent_client', sa.String(128), nullable=False),
    sa.Column('actor_id', sa.String(128), nullable=False),
    sa.Column('debug', sa.Boolean, nullable=False),
    sa.Column('state', sa.String(16), nullable=False),
    sa.Column('knowledge_revision', sa.Integer, nullable=False, server_default='0'),
    sa.CheckConstraint("state IN ('active','closed')"))

requirements = sa.Table('requirements', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('task_id', sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=True),
    sa.Column('request_id', sa.String(128)),
    sa.Column('web_request_id', sa.String(128)),
    sa.Column('original_text', sa.Text, nullable=False),
    sa.Column('current_text', sa.Text, nullable=False, server_default=''),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('version', sa.Integer, nullable=False),
    sa.Column('completion_summary', sa.Text),
    sa.UniqueConstraint('session_id', 'request_id', name='uq_requirement_submission'),
    sa.UniqueConstraint('project_id', 'web_request_id', name='uq_web_requirement_intake'),
    sa.Index('ix_requirements_task_active', 'task_id', 'status'),
    sa.CheckConstraint("status IN ('active','archived','deleted')", name='ck_requirements_status'))

findings = sa.Table('findings', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('task_id', sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('target_path', sa.Text, nullable=True),
    sa.Column('text', sa.Text, nullable=False),
    sa.Column('priority', sa.String(2), nullable=False),
    sa.Column('version', sa.Integer, nullable=False),
    sa.Column('status', sa.String(20), nullable=False),
    sa.UniqueConstraint('id', 'project_id', name='uq_findings_project'),
    sa.CheckConstraint("priority IN ('P0','P1','P2','P3')", name='ck_findings_priority'),
    sa.Index('ix_findings_scope', 'project_id', 'task_id', 'session_id', 'status'))

issues = sa.Table('issues', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('issue_type', sa.String(32), nullable=False),
    sa.Column('title', sa.String(500), nullable=False),
    sa.Column('description', sa.Text, nullable=False),
    sa.Column('file_path', sa.Text, nullable=False),
    sa.Column('related_rules_json', sa.Text, nullable=False),
    sa.Column('suggested_action', sa.Text, nullable=False),
    sa.Column('status', sa.String(20), nullable=False, server_default='open'))

agent_rule_state = sa.Table('agent_rule_state', metadata,
    sa.Column('rule_id', sa.ForeignKey('rules.id'), primary_key=True),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('evidence_version', sa.Integer, nullable=False),
    sa.Column('half_life_days', sa.Integer, nullable=False),
    sa.Column('revision_at', sa.String(40), nullable=False))

test_reports = sa.Table('test_reports', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('task_id', sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('request_id', sa.String(128), nullable=False),
    sa.Column('fingerprint', sa.String(64), nullable=False),
    sa.Column('command_json', sa.Text, nullable=False),
    sa.Column('paths_json', sa.Text, nullable=False),
    sa.Column('exit_code', sa.Integer, nullable=False),
    sa.Column('started_at', sa.String(40), nullable=False),
    sa.Column('finished_at', sa.String(40), nullable=False),
    sa.Column('recorded_at', sa.String(40), nullable=False),
    sa.Column('source', sa.String(24), nullable=False),
    sa.Column('test_cases_json', sa.Text, nullable=False, server_default='[]'),
    sa.UniqueConstraint('session_id','request_id', name='uq_test_request'),
    sa.UniqueConstraint('session_id','fingerprint', name='uq_test_unique_event'))

rule_observations = sa.Table('rule_observations', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('rule_id', sa.ForeignKey('rules.id'), nullable=False),
    sa.Column('evidence_version', sa.Integer, nullable=False),
    sa.Column('test_report_id', sa.ForeignKey('test_reports.id'), nullable=False),
    sa.Column('supports', sa.Boolean, nullable=False),
    sa.Column('check_ids_json', sa.Text, nullable=False, server_default='[]'),
    sa.Column('reason', sa.Text, nullable=False),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.UniqueConstraint('rule_id', 'evidence_version', 'test_report_id', name='uq_rule_evidence'))

requirement_versions = sa.Table('requirement_versions', metadata,
    sa.Column('requirement_id', sa.ForeignKey('requirements.id'), primary_key=True),
    sa.Column('version', sa.Integer, primary_key=True),
    sa.Column('original_text', sa.Text, nullable=False),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('completion_summary', sa.Text))

rules = sa.Table('rules', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('task_id', sa.ForeignKey('tasks.id')),
    sa.Column('title', sa.String(500), nullable=False),
    sa.Column('points_json', sa.Text, nullable=False),
    sa.Column('patterns_json', sa.Text, nullable=False),
    sa.Column('priority', sa.String(2), nullable=False),
    sa.Column('is_global', sa.Boolean, nullable=False, server_default='0'),
    sa.Column('priority_reason', sa.Text, nullable=False, server_default=''),
    sa.Column('validation_spec_json', sa.Text),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('version', sa.Integer, nullable=False),
    sa.Column('origin_rule_id', sa.ForeignKey('rules.id')),
    sa.Column('origin_version', sa.Integer),
    sa.Column('origin_reason', sa.Text),
    sa.UniqueConstraint('origin_rule_id','origin_version', name='uq_promotion_source_version'),
    sa.Index('ix_rules_effective', 'project_id', 'task_id', 'status', 'priority'),
    sa.UniqueConstraint('id', 'project_id', name='uq_rules_project'),
    sa.CheckConstraint("priority IN ('P0','P1','P2','P3')", name='ck_rules_priority'),
    sa.CheckConstraint("status IN ('draft','active','deprecated','revoked')"))

requirement_rule_links = sa.Table('requirement_rule_links', metadata,
    sa.Column('rule_id', sa.ForeignKey('rules.id'), primary_key=True),
    sa.Column('requirement_id', sa.ForeignKey('requirements.id'), nullable=False),
    sa.Index('ix_requirement_rule_links', 'requirement_id'))

contract_proposals = sa.Table('contract_proposals', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('task_id', sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('target_rule_id', sa.ForeignKey('rules.id'), nullable=False),
    sa.Column('target_version', sa.Integer, nullable=False),
    sa.Column('title', sa.String(500), nullable=False),
    sa.Column('points_json', sa.Text, nullable=False),
    sa.Column('patterns_json', sa.Text, nullable=False),
    sa.Column('priority', sa.String(2), nullable=False),
    sa.Column('category', sa.String(16)),  # Historical v1 proposals only; never used by v2.
    sa.Column('topics_json', sa.Text, nullable=False, server_default='[]'),
    sa.Column('is_global', sa.Boolean, nullable=False, server_default='0'),
    sa.Column('priority_reason', sa.Text, nullable=False, server_default=''),
    sa.Column('validation_spec_json', sa.Text),
    sa.Column('source_rule_id', sa.String(128)),
    sa.Column('source_version', sa.Integer),
    sa.Column('schema_version', sa.Integer, nullable=False, server_default='2'),
    sa.ForeignKeyConstraint(['source_rule_id', 'source_version'], ['rule_versions.rule_id', 'rule_versions.version']),
    sa.Column('reason', sa.Text, nullable=False),
    sa.Column('status', sa.String(16), nullable=False),
    sa.Column('decision_reason', sa.Text),
    sa.Column('reviewer_id', sa.String(128)),
    sa.Index('ix_contract_review', 'project_id', 'status'),
    sa.CheckConstraint("status IN ('pending','approved','rejected')"))

rule_versions = sa.Table('rule_versions', metadata,
    sa.Column('rule_id', sa.ForeignKey('rules.id'), primary_key=True),
    sa.Column('version', sa.Integer, primary_key=True),
    sa.Column('title', sa.String(500), nullable=False),
    sa.Column('points_json', sa.Text, nullable=False),
    sa.Column('patterns_json', sa.Text, nullable=False),
    sa.Column('priority', sa.String(2), nullable=False),
    sa.Column('category', sa.String(16)),  # Immutable v1 history, not a live classifier.
    sa.Column('topics_json', sa.Text, nullable=False, server_default='[]'),
    sa.Column('is_global', sa.Boolean, nullable=False, server_default='0'),
    sa.Column('priority_reason', sa.Text, nullable=False, server_default=''),
    sa.Column('validation_spec_json', sa.Text),
    sa.Column('schema_version', sa.Integer, nullable=False, server_default='2'),
    sa.Column('status', sa.String(16), nullable=False))

rule_reviews = sa.Table('rule_reviews', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False),
    sa.Column('rule_id', sa.String(128), nullable=False),
    sa.Column('rule_version', sa.Integer, nullable=False),
    sa.Column('approve', sa.Boolean, nullable=False),
    sa.Column('reason', sa.Text, nullable=False),
    sa.Column('reviewer_id', sa.String(128), nullable=False),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.ForeignKeyConstraint(['rule_id', 'rule_version'], ['rule_versions.rule_id', 'rule_versions.version']))

deliveries = sa.Table('deliveries', metadata,
    sa.Column('id', sa.String(128), primary_key=True),
    sa.Column('session_id', sa.ForeignKey('sessions.id'), nullable=False),
    sa.Column('request_id', sa.String(128), nullable=False),
    sa.Column('fingerprint', sa.String(64), nullable=False),
    sa.Column('response_json', sa.Text, nullable=False),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.UniqueConstraint('session_id','request_id', name='uq_delivery_request'))

delivery_rules = sa.Table('delivery_rules', metadata,
    sa.Column('delivery_id', sa.ForeignKey('deliveries.id'), primary_key=True),
    sa.Column('rule_id', sa.String(128), primary_key=True),
    sa.Column('version', sa.Integer, nullable=False),
    sa.Column('representation', sa.String(16), nullable=False),
    sa.ForeignKeyConstraint(['rule_id','version'],['rule_versions.rule_id','rule_versions.version']))

delivery_requirements = sa.Table('delivery_requirements', metadata,
    sa.Column('delivery_id', sa.ForeignKey('deliveries.id'), primary_key=True),
    sa.Column('requirement_id', sa.String(128), primary_key=True),
    sa.Column('version', sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(['requirement_id','version'], ['requirement_versions.requirement_id','requirement_versions.version']))

delivery_findings = sa.Table('delivery_findings', metadata,
    sa.Column('delivery_id', sa.ForeignKey('deliveries.id'), primary_key=True),
    sa.Column('finding_id', sa.ForeignKey('findings.id'), primary_key=True),
    sa.Column('version', sa.Integer, nullable=False))

feedback = sa.Table('feedback', metadata,
    sa.Column('delivery_id', sa.String(128), primary_key=True),
    sa.Column('rule_id', sa.String(128), primary_key=True),
    sa.Column('rule_version', sa.Integer, nullable=False),
    sa.Column('score', sa.Integer, nullable=False),
    sa.Column('reason', sa.Text, nullable=False),
    sa.ForeignKeyConstraint(['delivery_id','rule_id'],['delivery_rules.delivery_id','delivery_rules.rule_id']),
    sa.CheckConstraint('score >= 0 AND score <= 5'))

audit = sa.Table('audit', metadata,
    sa.Column('sequence', sa.Integer, primary_key=True, autoincrement=True),
    sa.Column('project_id', sa.ForeignKey('projects.id'), nullable=False, index=True),
    sa.Column('actor', sa.String(128), nullable=False),
    sa.Column('action', sa.String(100), nullable=False),
    sa.Column('entity_id', sa.String(128), nullable=False),
    sa.Column('details_json', sa.Text, nullable=False),
    sa.Column('created_at', sa.String(40), nullable=False))
