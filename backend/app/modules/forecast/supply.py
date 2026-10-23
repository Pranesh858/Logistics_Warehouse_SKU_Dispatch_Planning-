"""Supplier lead times, and what is already on its way.

Ordering has to answer "how much do I need so I do not run out before the next delivery arrives", not
"how much will I sell this week". Two things the old calculation ignored:

  * **Lead time** - stock ordered today arrives days later, so the order must cover demand during the wait
    as well as the period after it. Without this, anything slow to deliver is systematically under-ordered.
  * **Stock already on order** - a purchase order raised yesterday is coming. Counting it stops the same
    units being ordered again every day until they arrive.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.integrations.models import PurchaseOrder
from app.shared.exceptions import BadRequestError, NotFoundError

MAX_LEAD_DAYS = 30


class LeadTime(Base):
    """How many days this SKU takes to arrive after it is ordered. Anything not listed uses the default."""

    __tablename__ = "supplier_lead_times"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    supplier: Mapped[str] = mapped_column(String(120), default="")
    updated_by: Mapped[str] = mapped_column(String(60), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


async def lead_times(db: AsyncSession) -> dict[int, int]:
    rows = (await db.execute(select(LeadTime))).scalars().all()
    return {r.product_id: r.lead_time_days for r in rows}


async def list_lead_times(db: AsyncSession) -> dict:
    rows = (await db.execute(select(LeadTime).order_by(LeadTime.product_id))).scalars().all()
    return {
        "default_days": settings.default_lead_time_days,
        "skus": [{"product_id": r.product_id, "lead_time_days": r.lead_time_days, "supplier": r.supplier,
                  "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
                 for r in rows],
    }


async def set_lead_time(db: AsyncSession, product_id: int, days: int, supplier: str, user: str) -> dict:
    if days < 0 or days > MAX_LEAD_DAYS:
        raise BadRequestError(f"Lead time must be between 0 and {MAX_LEAD_DAYS} days")
    known = set(runtime_products())
    if known and product_id not in known:
        raise BadRequestError(f"SKU {product_id} is not in the catalogue")
    row = await db.get(LeadTime, product_id)
    if row is None:
        row = LeadTime(product_id=product_id)
        db.add(row)
    row.lead_time_days, row.supplier, row.updated_by = days, supplier.strip(), user
    row.updated_at = datetime.now()
    await db.commit()
    return {"product_id": product_id, "lead_time_days": days, "supplier": row.supplier}


async def clear_lead_time(db: AsyncSession, product_id: int) -> None:
    row = await db.get(LeadTime, product_id)
    if row is None:
        raise NotFoundError("That SKU has no lead time of its own")
    await db.delete(row)
    await db.commit()


def runtime_products() -> set[int]:
    from app.modules.forecast.runtime import runtime
    try:
        return set(int(p) for p in runtime.frame["product_id"].unique())
    except Exception:
        return set()


async def on_order(db: AsyncSession) -> dict[tuple[int, str], float]:
    """Units sitting on purchase orders that were sent and have not been received yet."""
    rows = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.status == "SENT",
                                                         PurchaseOrder.received_at.is_(None)))).scalars().all()
    out: dict[tuple[int, str], float] = {}
    for po in rows:
        for line in po.lines or []:
            try:
                key = (int(line["product_id"]), po.warehouse_id)
                out[key] = out.get(key, 0.0) + float(line["units"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


async def receive(db: AsyncSession, po_id: int, user: str) -> PurchaseOrder:
    """The goods arrived. They stop counting as on order; the WMS stock feed reports the new shelf figure."""
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError("Purchase order not found")
    if po.status != "SENT":
        raise BadRequestError("Only a purchase order that reached the ERP can be received")
    if po.received_at is not None:
        raise BadRequestError("This purchase order was already received")
    po.received_at = datetime.now()
    po.received_by = user
    await db.commit()
    await db.refresh(po)
    return po
