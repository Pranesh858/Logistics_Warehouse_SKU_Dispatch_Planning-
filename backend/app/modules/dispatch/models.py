from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Plan lifecycle:  RECOMMENDED -> (planner approves) -> EXPORTED | PARTIALLY_EXPORTED
#                  RECOMMENDED -> SUPERSEDED  (a newer recommendation replaced it before approval)
PLAN_RECOMMENDED = "RECOMMENDED"
PLAN_SUPERSEDED = "SUPERSEDED"
PLAN_EXPORTED = "EXPORTED"
PLAN_PARTIAL = "PARTIALLY_EXPORTED"
PLAN_NOTHING = "APPROVED_NOTHING_TO_SEND"


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_timestamp: Mapped[datetime] = mapped_column(DateTime)
    customer_id: Mapped[str] = mapped_column(String(40))
    customer_tier: Mapped[str] = mapped_column(String(20))
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse_id: Mapped[str] = mapped_column(String(10), index=True)
    qty_ordered: Mapped[float] = mapped_column(Float)
    due_date: Mapped[datetime] = mapped_column(DateTime)


class BlockedSku(Base):
    __tablename__ = "blocked_skus"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer)
    warehouse_id: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Truck(Base):
    """A truck the planner configures. It loads from one warehouse. Removing a truck only switches it off, so old plans keep their history."""

    __tablename__ = "trucks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    warehouse_id: Mapped[str] = mapped_column(String(10), index=True)
    capacity_units: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TruckLoad(Base):
    """Part (or all) of an order carried by one truck in one plan."""

    __tablename__ = "dispatch_truck_loads"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dispatch_plans.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    truck_id: Mapped[int] = mapped_column(Integer, index=True)
    qty: Mapped[float] = mapped_column(Float)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)   # planner picked this truck


class Plan(Base):
    __tablename__ = "dispatch_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    trigger: Mapped[str] = mapped_column(String(60))          # startup / new_orders / recalculate ...
    wave_capacity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list["PlanLine"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class PlanLine(Base):
    __tablename__ = "dispatch_plan_lines"
    __table_args__ = (UniqueConstraint("plan_id", "order_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dispatch_plans.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    order_timestamp: Mapped[datetime] = mapped_column(DateTime)
    customer_id: Mapped[str] = mapped_column(String(40))
    customer_tier: Mapped[str] = mapped_column(String(20))
    product_id: Mapped[int] = mapped_column(Integer)
    warehouse_id: Mapped[str] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(60), nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime)
    wave_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qty_ordered: Mapped[float] = mapped_column(Float)
    qty_allocated: Mapped[float] = mapped_column(Float)       # what the engine recommends
    qty_short: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))           # FULL PARTIAL HELD BACKORDERED BLOCKED WAVE_OVERFLOW COMMITTED
    at_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    rules_applied: Mapped[str] = mapped_column(Text, default="")
    exception_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # planner review (all optional: leaving a line alone = accept the recommendation)
    decision: Mapped[str | None] = mapped_column(String(12), nullable=True)   # APPROVED OVERRIDDEN REJECTED
    override_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="lines")


class LedgerEntry(Base):
    """Stock promised to an approved order (SENT to the WMS, or FAILED and awaiting retry). Never re-allocated."""

    __tablename__ = "allocation_ledger"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse_id: Mapped[str] = mapped_column(String(10), index=True)
    qty_committed: Mapped[float] = mapped_column(Float)
    customer_tier: Mapped[str] = mapped_column(String(20))
    committed_decision: Mapped[str] = mapped_column(String(12))
    wms_status: Mapped[str] = mapped_column(String(10), default="FAILED")   # SENT | FAILED (stock stays reserved either way)
    # RESERVED while the goods are still on the shelf; SHIPPED or CANCELLED once the WMS says what happened.
    # Only RESERVED rows hold stock back, so a shipment is never counted twice.
    fulfilment: Mapped[str] = mapped_column(String(10), default="RESERVED", index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan_id: Mapped[int] = mapped_column(Integer)
    committed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExportLog(Base):
    __tablename__ = "wms_export_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    qty: Mapped[float] = mapped_column(Float)
    export_status: Mapped[str] = mapped_column(String(12))    # SUCCESS FAILED CONFLICT
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
