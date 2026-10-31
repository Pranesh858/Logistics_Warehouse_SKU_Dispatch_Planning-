"""Connected systems: the kind of system on the other end, so an ERPNext site can be connected as the ERP.

Revision ID: f4b8d2e61a37
Revises: e7a3c1d95b20
"""
import sqlalchemy as sa
from alembic import op

revision = 'f4b8d2e61a37'
down_revision = 'e7a3c1d95b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('integration_settings',
                  sa.Column('kind', sa.String(length=20), nullable=False, server_default='generic'))


def downgrade() -> None:
    op.drop_column('integration_settings', 'kind')
