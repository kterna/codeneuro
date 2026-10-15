"""Topic CRUD, explicit priority sets and independent validation (protocol v2).

No business classification is guessed. Existing projects remain topic-query disabled.
Run on an explicitly selected database; migrations/env.py owns the FK/transaction boundary.
"""
from alembic import op
import sqlalchemy as sa

revision = '2c4e8a6b901d'
down_revision = '1f7a79740655'
branch_labels = None
depends_on = None


def old_table(name, remove_checks=()):
    # copy_from describes the existing columns, never the final expanded schema.
    table = sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())
    checks = sorted((c for c in table.constraints if isinstance(c, sa.CheckConstraint)),
                    key=lambda c: str(c.sqltext))
    for index, constraint in enumerate(checks):
        if any(token in str(constraint.sqltext) for token in remove_checks):
            table.constraints.remove(constraint)
        elif constraint.name is None:
            constraint.name = f'ck_{name}_retained_{index}'
    return table


def snapshot_columns(batch):
    batch.add_column(sa.Column('topics_json', sa.Text(), nullable=False, server_default='[]'))
    batch.add_column(sa.Column('is_global', sa.Boolean(), nullable=False, server_default='0'))
    batch.add_column(sa.Column('priority_reason', sa.Text(), nullable=False, server_default=''))
    batch.add_column(sa.Column('validation_spec_json', sa.Text(), nullable=True))
    batch.add_column(sa.Column('schema_version', sa.Integer(), nullable=False, server_default='2'))
    # Historical category values remain immutable; new snapshots leave this column NULL.
    batch.alter_column('category', existing_type=sa.String(16), nullable=True)


def upgrade():
    op.add_column('projects', sa.Column('taxonomy_revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('topic_query_enabled', sa.Boolean(), nullable=False, server_default='0'))
    op.create_table('project_topics',
        sa.Column('project_id', sa.String(128), sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('definition_locked', sa.Boolean(), nullable=False, server_default='0'),
        sa.CheckConstraint("status IN ('active','deleted')", name='ck_topics_status'))
    with op.batch_alter_table('rules', recreate='always',
                             copy_from=old_table('rules', ('category', 'priority'))) as batch:
        batch.drop_column('category')
        batch.add_column(sa.Column('is_global', sa.Boolean(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('priority_reason', sa.Text(), nullable=False, server_default=''))
        batch.add_column(sa.Column('validation_spec_json', sa.Text(), nullable=True))
        batch.create_check_constraint('ck_rules_priority', "priority IN ('P0','P1','P2','P3')")
        batch.create_unique_constraint('uq_rules_project', ['id', 'project_id'])
    with op.batch_alter_table('findings', recreate='always', copy_from=old_table('findings', ('priority',))) as batch:
        batch.alter_column('target_path', existing_type=sa.Text(), nullable=True)
        batch.create_unique_constraint('uq_findings_project', ['id', 'project_id'])
        batch.create_check_constraint('ck_findings_priority', "priority IN ('P0','P1','P2','P3')")
    with op.batch_alter_table('rule_versions', recreate='always', copy_from=old_table('rule_versions')) as batch:
        snapshot_columns(batch)
    # All rows present during this offline upgrade are v1; future inserts default to v2.
    op.execute(sa.text('UPDATE rule_versions SET schema_version = 1'))
    with op.batch_alter_table('contract_proposals', recreate='always', copy_from=old_table('contract_proposals')) as batch:
        snapshot_columns(batch)
        batch.add_column(sa.Column('source_rule_id', sa.String(128), nullable=True))
        batch.add_column(sa.Column('source_version', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_proposal_candidate_version', 'rule_versions',
                                 ['source_rule_id', 'source_version'], ['rule_id', 'version'])
    op.execute(sa.text('UPDATE contract_proposals SET schema_version = 1'))
    for table, entity, parent, index in (
        ('rule_topics', 'rule_id', 'rules', 'ix_rule_topics_lookup'),
        ('finding_topics', 'finding_id', 'findings', 'ix_finding_topics_lookup'),
    ):
        op.create_table(table,
            sa.Column('project_id', sa.String(128), nullable=False),
            sa.Column(entity, sa.String(128), primary_key=True),
            sa.Column('topic_key', sa.String(64), primary_key=True),
            sa.ForeignKeyConstraint([entity, 'project_id'], [parent + '.id', parent + '.project_id']),
            sa.ForeignKeyConstraint(['project_id', 'topic_key'], ['project_topics.project_id', 'project_topics.key']))
        op.create_index(index, table, ['project_id', 'topic_key'])
    op.add_column('test_reports', sa.Column('test_cases_json', sa.Text(), nullable=False, server_default='[]'))
    op.add_column('rule_observations', sa.Column('check_ids_json', sa.Text(), nullable=False, server_default='[]'))
    op.create_table('rule_reviews',
        sa.Column('id', sa.String(128), primary_key=True),
        sa.Column('project_id', sa.String(128), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('rule_id', sa.String(128), nullable=False),
        sa.Column('rule_version', sa.Integer(), nullable=False),
        sa.Column('approve', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('reviewer_id', sa.String(128), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(['rule_id', 'rule_version'], ['rule_versions.rule_id', 'rule_versions.version']))


def downgrade():
    raise RuntimeError('V2 topics, P3 and evidence cannot be losslessly downgraded. Restore a reviewed backup instead.')
