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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, server_default=func.now())


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


async def reserved(db: AsyncSession) -> dict[tuple[int, str], float]:
    """Stock already promised to approved orders that are still on the shelf."""
    from app.modules.dispatch.models import LedgerEntry
    q = (select(LedgerEntry.product_id, LedgerEntry.warehouse_id, func.sum(LedgerEntry.qty_committed))
         .where(LedgerEntry.fulfilment == "RESERVED")
         .group_by(LedgerEntry.product_id, LedgerEntry.warehouse_id))
    return {(int(p), w): float(q_) for p, w, q_ in (await db.execute(q)).all()}


# Lines the current plan cannot fill from the shelf. WAVE_OVERFLOW is short of truck space, not stock, and BLOCKED
# is a SKU the planner stopped on purpose, so neither is a reason to buy more.
SHORT_STATUSES = ("PARTIAL", "HELD", "BACKORDERED")


async def waiting(db: AsyncSession) -> dict[tuple[int, str], float]:
    """Units customers have already ordered that the current plan cannot fill from the shelf, per SKU x warehouse.
    The forecast only looks ahead, so without this an order short by 63 units never reached the ordering list."""
    from app.modules.dispatch.models import PLAN_RECOMMENDED, Plan, PlanLine
    plan = (await db.execute(select(Plan).where(Plan.status == PLAN_RECOMMENDED)
                             .order_by(Plan.version.desc()))).scalars().first()
    if plan is None:
        return {}
    rows = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan.id, PlanLine.status.in_(SHORT_STATUSES),
                                                    PlanLine.qty_short > 0))).scalars().all()
    out: dict[tuple[int, str], float] = {}
    for ln in rows:
        if ln.decision == "REJECTED":              # the planner turned the order down: nobody is waiting for it
            continue
        key = (int(ln.product_id), ln.warehouse_id)
        out[key] = out.get(key, 0.0) + float(ln.qty_short)
    return out


async def order_inputs(db: AsyncSession) -> dict:
    """Everything Units to order needs besides the forecast. The list, Send to ERP and the stock alerts all take it
    from here, so they agree (Send to ERP used to leave out what was already on order and the lead times)."""
    return {"reserved": await reserved(db), "lead_times": await lead_times(db),
            "default_lead": settings.default_lead_time_days, "on_order": await on_order(db), "waiting": await waiting(db)}


async def receive(db: AsyncSession, po_id: int, user: str) -> PurchaseOrder:
    """The goods arrived: they stop counting as on order and go onto the shelf, as a RECEIPT on the stock ledger.

    The WMS is told first. Its count is the one our stock sync copies, so goods booked in here only would be
    taken away again by its next report (seen in the demo: received stock fell back within a minute). If the WMS
    cannot take the receipt, nothing is recorded and the planner can try again; it ignores a reference it has."""
    from app.integrations import clients
    from app.modules.dispatch import service as dispatch_service
    from app.modules.stock import service as stock_ledger
    from app.modules.stock.models import RECEIPT

    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError("Purchase order not found")
    if po.status != "SENT":
        raise BadRequestError("Only a purchase order that reached the ERP can be received")
    if po.received_at is not None:
        raise BadRequestError("This purchase order was already received")
    wms = clients.inventory_source()
    if hasattr(wms, "receive"):
        try:
            await wms.receive({"reference": po.po_ref, "warehouse_id": po.warehouse_id,
                               "lines": [{"product_id": int(ln["product_id"]), "units": float(ln["units"])}
                                         for ln in po.lines or []]})
        except clients.IntegrationError as exc:
            raise BadRequestError(f"The WMS did not take the goods in, so nothing was received: {exc}") from exc
    po.received_at = datetime.now()
    po.received_by = user
    await db.commit()
    moves = [stock_ledger.Move(int(ln["product_id"]), po.warehouse_id, float(ln["units"]), RECEIPT, ref=po.po_ref)
             for ln in po.lines or []]
    if await stock_ledger.apply(db, moves, source="purchase", username=user):
        await dispatch_service.note_change(db, "purchase_received")
    await db.refresh(po)
    return po
