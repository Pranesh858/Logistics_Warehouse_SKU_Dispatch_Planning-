"""Plans are rebuilt only on Generate plan: plan_changes lists what happened since the current plan was built.

Revision ID: a9c5e3f71b48
Revises: f4b8d2e61a37
"""
import sqlalchemy as sa
from alembic import op

revision = 'a9c5e3f71b48'
down_revision = 'f4b8d2e61a37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'plan_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('detail', sa.String(length=60), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('plan_changes')
