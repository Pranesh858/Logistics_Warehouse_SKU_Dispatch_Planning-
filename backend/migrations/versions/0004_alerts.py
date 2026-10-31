"""Alerts: one row per problem, deduplicated by key.

Revision ID: c4e8a5b71d92
Revises: b1c7f2a9d430
"""
import sqlalchemy as sa
from alembic import op

revision = 'c4e8a5b71d92'
down_revision = 'b1c7f2a9d430'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=160), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=14), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('warehouse_id', sa.String(length=10), nullable=True),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('occurrences', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('last_seen', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('acknowledged_by', sa.String(length=60), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_note', sa.Text(), nullable=True),
        sa.Column('delivery', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alerts_dedupe_key', 'alerts', ['dedupe_key'], unique=True)
    op.create_index('ix_alerts_kind', 'alerts', ['kind'])
    op.create_index('ix_alerts_severity', 'alerts', ['severity'])
    op.create_index('ix_alerts_status', 'alerts', ['status'])
    op.create_index('ix_alerts_warehouse_id', 'alerts', ['warehouse_id'])
    op.create_index('ix_alerts_last_seen', 'alerts', ['last_seen'])


def downgrade() -> None:
    for name in ('ix_alerts_last_seen', 'ix_alerts_warehouse_id', 'ix_alerts_status',
                 'ix_alerts_severity', 'ix_alerts_kind', 'ix_alerts_dedupe_key'):
        op.drop_index(name, table_name='alerts')
    op.drop_table('alerts')
