"""Stock and master data in tables: warehouses, SKUs and the stock movement history.

stock_levels already exists; from this revision it holds the stock of every stocked SKU x warehouse pair rather
than only the figures a WMS reported. The rows are filled by the application on its next start (from the seed
files), with an OPENING movement for each, so no data is moved here.

Revision ID: d2f6b9c4e801
Revises: c4e8a5b71d92
"""
import sqlalchemy as sa
from alembic import op

revision = 'd2f6b9c4e801'
down_revision = 'c4e8a5b71d92'
branch_labels = None
depends_on = None

MOVEMENT_INDEXES = ('product_id', 'warehouse_id', 'kind', 'at')


def upgrade() -> None:
    op.create_table(
        'warehouses',
        sa.Column('warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('city', sa.String(length=60), nullable=False),
        sa.PrimaryKeyConstraint('warehouse_id'),
    )
    op.create_table(
        'skus',
        sa.Column('product_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=60), nullable=False),
        sa.Column('is_organic', sa.Boolean(), nullable=False),
        sa.Column('shelf_life_days', sa.Integer(), nullable=True),
        sa.Column('weight_g', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('product_id'),
    )
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('warehouse_id', sa.String(length=10), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('qty_after', sa.Float(), nullable=False),
        sa.Column('ref', sa.String(length=60), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('username', sa.String(length=60), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in MOVEMENT_INDEXES:
        op.create_index(f'ix_stock_movements_{col}', 'stock_movements', [col])


def downgrade() -> None:
    for col in MOVEMENT_INDEXES:
        op.drop_index(f'ix_stock_movements_{col}', table_name='stock_movements')
    op.drop_table('stock_movements')
    op.drop_table('skus')
    op.drop_table('warehouses')
