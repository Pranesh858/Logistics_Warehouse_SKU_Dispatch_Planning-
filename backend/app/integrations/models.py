from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockLevel(Base):
    """Latest stock the WMS reported for a SKU at a warehouse. Wins over the stock in the sales history."""

    __tablename__ = "stock_levels"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    qty: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="wms")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IntegrationRun(Base):
    """One attempt to pull from (or receive from) an outside system. Drives the Integrations page."""

    __tablename__ = "integration_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feed: Mapped[str] = mapped_column(String(20), index=True)       # inventory | orders | sales | purchasing
    mode: Mapped[str] = mapped_column(String(10))                    # simulator | live | webhook
    status: Mapped[str] = mapped_column(String(10))                  # OK | FAILED
    rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IntegrationSetting(Base):
    """Connection details an admin enters in the app, so a new WMS or ERP can be connected without touching code.
    What is stored here wins over the values in .env."""

    __tablename__ = "integration_settings"

    system: Mapped[str] = mapped_column(String(10), primary_key=True)     # wms | erp
    base_url: Mapped[str] = mapped_column(String(300), default="")
    api_key: Mapped[str] = mapped_column(String(300), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)         # off = keep using the simulator
    field_map: Mapped[dict] = mapped_column(JSON, default=dict)           # {"inventory": {"product_id": "sku"}, ...}
    sync_minutes: Mapped[dict] = mapped_column(JSON, default=dict)        # {"inventory": 5, "orders": 5, "sales": 1440}
    updated_by: Mapped[str] = mapped_column(String(60), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PurchaseOrder(Base):
    """A purchase order raised from the Units to order list and sent to the ERP."""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_ref: Mapped[str] = mapped_column(String(40), unique=True)
    warehouse_id: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(10))                  # SENT | FAILED
    erp_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    total_units: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list] = mapped_column(JSON)
    period_days: Mapped[int] = mapped_column(Integer)
    safety_buffer: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    # Until the goods arrive these units count as "on order", so the same SKU is not ordered again tomorrow.
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
