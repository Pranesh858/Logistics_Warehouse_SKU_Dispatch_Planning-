"""Dispatch waves: each plan records the wave it was built for, e.g. "2026-10-31 Morning".

Older plans keep NULL: they were built before waves and covered every open order.

Revision ID: e7a3c1d95b20
Revises: d2f6b9c4e801
"""
import sqlalchemy as sa
from alembic import op

revision = 'e7a3c1d95b20'
down_revision = 'd2f6b9c4e801'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('dispatch_plans', sa.Column('wave', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('dispatch_plans', 'wave')
