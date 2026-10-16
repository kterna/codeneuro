"""Resource CRUD: soft-deletion states and separately preserved original demand text."""
from alembic import op
import sqlalchemy as sa

revision = '3d5f9b7c012e'
down_revision = '2c4e8a6b901d'
branch_labels = None
depends_on = None


def upgrade():
    for name, states in (
        ('tasks', "'draft','active','testing','paused','released','archived','deleted'"),
        ('requirements', "'active','archived','deleted'"),
    ):
        table = sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())
        for index, constraint in enumerate(list(table.constraints)):
            if isinstance(constraint, sa.CheckConstraint):
                if 'status IN' in str(constraint.sqltext):
                    table.constraints.remove(constraint)
                elif constraint.name is None:
                    constraint.name = f'ck_{name}_retained_{index}'
        with op.batch_alter_table(name, recreate='always', copy_from=table) as batch:
            batch.create_check_constraint(f'ck_{name}_status', f'status IN ({states})')
            if name == 'requirements':
                batch.add_column(sa.Column('current_text', sa.Text(), nullable=False, server_default=''))
    op.execute(sa.text('UPDATE requirements SET current_text = original_text'))


def downgrade():
    raise RuntimeError('Soft deletion and revised demands cannot be losslessly downgraded. Restore a reviewed backup.')
