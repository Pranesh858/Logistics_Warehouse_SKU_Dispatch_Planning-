"""Master data and the stock ledger.

The current figure per SKU x warehouse lives in `stock_levels` (app.integrations.models.StockLevel). Every change
to it is also written here as a movement, in the same transaction, so the figure can always be explained:
opening stock plus the sum of the movements is what is on the shelf.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

OPENING = "OPENING"              # the figure the system started from
RECEIPT = "RECEIPT"              # goods in from a supplier (a purchase order received)
SHIPMENT = "SHIPMENT"            # goods out to a customer (the WMS confirmed the order shipped)
ADJUSTMENT = "ADJUSTMENT"        # a count (WMS report, manual count) replaced what we thought was there
TRANSFER_OUT = "TRANSFER_OUT"    # left on a transfer to another warehouse
TRANSFER_IN = "TRANSFER_IN"      # arrived on a transfer from another warehouse
TRANSFER_RETURN = "TRANSFER_RETURN"  # a transfer turned back: the goods are on the donor's shelf again
KINDS = (OPENING, RECEIPT, SHIPMENT, ADJUSTMENT, TRANSFER_OUT, TRANSFER_IN, TRANSFER_RETURN)


class Warehouse(Base):
    __tablename__ = "warehouses"

    warehouse_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    city: Mapped[str] = mapped_column(String(60))


class Sku(Base):
    __tablename__ = "skus"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    product_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    is_organic: Mapped[bool] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse_id: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    qty: Mapped[float] = mapped_column(Float)              # signed: + onto the shelf, - off it
    qty_after: Mapped[float] = mapped_column(Float)        # the shelf figure once this movement is applied
    ref: Mapped[str | None] = mapped_column(String(60), nullable=True)     # order id, transfer ref or PO ref
    source: Mapped[str] = mapped_column(String(20))        # manual, webhook, wms, dispatch, transfer, purchase, seed
    username: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
