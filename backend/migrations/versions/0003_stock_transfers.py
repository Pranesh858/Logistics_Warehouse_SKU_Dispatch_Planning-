"""Cross-warehouse stock transfers and the transit times between warehouses.

Revision ID: b1c7f2a9d430
Revises: fda4453ee48c
"""
import sqlalchemy as sa
from alembic import op

revision = 'b1c7f2a9d430'
down_revision = 'fda4453ee48c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transfer_ref', sa.String(length=40), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('from_warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('to_warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('transit_days', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('short_orders', sa.Integer(), nullable=False),
        sa.Column('earliest_due', sa.DateTime(), nullable=True),
        sa.Column('eta', sa.DateTime(), nullable=True),
        sa.Column('plan_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('approved_by', sa.String(length=60), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('received_by', sa.String(length=60), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', sa.String(length=60), nullable=True),
        sa.Column('cancel_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transfer_ref'),
    )
    op.create_index('ix_stock_transfers_product_id', 'stock_transfers', ['product_id'])
    op.create_index('ix_stock_transfers_from_warehouse_id', 'stock_transfers', ['from_warehouse_id'])
    op.create_index('ix_stock_transfers_to_warehouse_id', 'stock_transfers', ['to_warehouse_id'])
    op.create_index('ix_stock_transfers_status', 'stock_transfers', ['status'])

    op.create_table(
        'warehouse_transfer_lanes',
        sa.Column('from_warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('to_warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('transit_days', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.String(length=60), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('from_warehouse_id', 'to_warehouse_id'),
    )


def downgrade() -> None:
    op.drop_table('warehouse_transfer_lanes')
    op.drop_index('ix_stock_transfers_status', table_name='stock_transfers')
    op.drop_index('ix_stock_transfers_to_warehouse_id', table_name='stock_transfers')
    op.drop_index('ix_stock_transfers_from_warehouse_id', table_name='stock_transfers')
    op.drop_index('ix_stock_transfers_product_id', table_name='stock_transfers')
    op.drop_table('stock_transfers')
