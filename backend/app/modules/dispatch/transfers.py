"""Cross-warehouse stock transfers.

The allocation engine fills each order from its own warehouse, because that is where the goods are. That
leaves a real gap: WH02 reports an order BACKORDERED while WH05 has the same SKU sitting spare. Moving stock
between warehouses closes it, but it is a physical move that takes days, so it cannot rescue an order due
this afternoon and it must not happen behind the planner's back.

    recommended plan ->  proposals raised from the shortages it reports (nothing moves)
    planner approves ->  the goods leave: the donor's stock drops now and an ETA is set
    goods arrive     ->  received: the destination's stock rises and the plan is rebuilt

Only stock a donor can genuinely spare is ever offered: free stock after its own commitments and
allocations, less a buffer of its own recent demand, so a transfer never causes the next shortage.
"""
import asyncio
import secrets
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.dispatch import engine, stockview
from app.modules.dispatch.models import (
    TRANSFER_CANCELLED, TRANSFER_IN_TRANSIT, TRANSFER_PROPOSED, TRANSFER_RECEIVED,
    BlockedSku, LedgerEntry, PlanLine, StockTransfer, TransferLane,
)
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError, NotFoundError

DEMAND_WINDOW_DAYS = 28
MAX_TRANSIT_DAYS = 30
OPEN_STATUSES = (TRANSFER_PROPOSED, TRANSFER_IN_TRANSIT)


# ----------------------------------------------------------------- inputs the engine needs
def daily_demand() -> dict[tuple[int, str], float]:
    """Average units sold per day per SKU x warehouse over the recent past.

    This sets the buffer a donor keeps for itself. Taken from the sales history rather than the forecast on
    purpose: it is a floor, and a plain recent average is harder to argue with than a model's opinion.
    """
    try:
        frame = runtime.frame
    except Exception:
        return {}
    cutoff = frame["date"].max() - pd.Timedelta(days=DEMAND_WINDOW_DAYS)
    recent = frame[frame["date"] > cutoff]
    if not len(recent):
        return {}
    avg = recent.groupby(["product_id", "warehouse_id"], observed=True)["units_sold"].mean()
    return {(int(pid), wh): float(v) for (pid, wh), v in avg.items()}


async def lane_map(db: AsyncSession) -> dict[tuple[str, str], int]:
    rows = (await db.execute(select(TransferLane))).scalars().all()
    return {(r.from_warehouse_id, r.to_warehouse_id): r.transit_days for r in rows}


async def incoming(db: AsyncSession) -> dict[tuple[int, str], float]:
    """Units on their way in, per (product_id, destination). They already cover part of a shortage."""
    rows = (await db.execute(select(StockTransfer).where(StockTransfer.status == TRANSFER_IN_TRANSIT))).scalars().all()
    out: dict[tuple[int, str], float] = {}
    for t in rows:
        key = (int(t.product_id), t.to_warehouse_id)
        out[key] = out.get(key, 0.0) + float(t.qty)
    return out


async def held(db: AsyncSession) -> dict[tuple[int, str], float]:
    """Units the ledger holds back: reserved against an approved order, still physically on the shelf."""
    rows = (await db.execute(select(LedgerEntry).where(LedgerEntry.fulfilment == "RESERVED"))).scalars().all()
    out: dict[tuple[int, str], float] = {}
    for r in rows:
        key = (int(r.product_id), r.warehouse_id)
        out[key] = out.get(key, 0.0) + float(r.qty_committed)
    return out


EMPTY_PLAN = ["order_id", "order_timestamp", "product_id", "warehouse_id",
              "qty_allocated", "qty_short", "status", "due_date"]


async def _plan_frame(db: AsyncSession, plan) -> pd.DataFrame:
    """The plan's lines, read explicitly: plan.lines is a lazy relationship and would not load here."""
    if plan is None:
        return pd.DataFrame(columns=EMPTY_PLAN)
    lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan.id))).scalars().all()
    df = pd.DataFrame([{
        "order_id": ln.order_id, "order_timestamp": ln.order_timestamp, "product_id": ln.product_id,
        "warehouse_id": ln.warehouse_id, "qty_allocated": ln.qty_allocated, "qty_short": ln.qty_short,
        "status": ln.status, "due_date": ln.due_date,
    } for ln in lines], columns=EMPTY_PLAN)
    if len(df):
        for c in ("order_timestamp", "due_date"):
            df[c] = pd.to_datetime(df[c])
    return df


def _ref(dest: str) -> str:
    return f"TR-{dest}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}"


# ----------------------------------------------------------------- proposals
async def refresh_proposals(db: AsyncSession, plan) -> int:
    """Replace the outstanding proposals with ones raised from this plan. Returns how many now stand.

    Proposals are advice about the current plan, so a new plan replaces them wholesale rather than leaving
    stale suggestions behind. Transfers already in transit are untouched: those goods have left.
    """
    if not settings.propose_transfers or plan is None:
        return 0
    await db.execute(delete(StockTransfer).where(StockTransfer.status == TRANSFER_PROPOSED))
    plan_df = await _plan_frame(db, plan)
    if not len(plan_df):
        await db.commit()
        return 0

    stock = await asyncio.to_thread(runtime.stock_snapshot)
    blocked = {(b.product_id, b.warehouse_id) for b in (await db.execute(select(BlockedSku))).scalars()}
    reserved, lanes, coming = await held(db), await lane_map(db), await incoming(db)
    demand = await asyncio.to_thread(daily_demand)

    proposals = await asyncio.to_thread(
        lambda: engine.propose_transfers(
            plan_df, stock, committed=reserved, daily_demand=demand, lanes=lanes,
            default_days=settings.default_transfer_days, keep_days=settings.transfer_keep_days,
            min_units=settings.min_transfer_units, now=datetime.now(), blocked=blocked, incoming=coming,
        ))
    for r in proposals.itertuples():
        db.add(StockTransfer(
            transfer_ref=_ref(r.to_warehouse_id), product_id=int(r.product_id),
            from_warehouse_id=r.from_warehouse_id, to_warehouse_id=r.to_warehouse_id, qty=float(r.qty),
            transit_days=int(r.transit_days), status=TRANSFER_PROPOSED, reason=r.reason,
            short_orders=int(r.short_orders), earliest_due=pd.Timestamp(r.earliest_due).to_pydatetime(),
            eta=pd.Timestamp(r.eta).to_pydatetime(), plan_id=plan.id,
        ))
    await db.commit()
    return len(proposals)


# ----------------------------------------------------------------- reading
def view(t: StockTransfer) -> dict:
    return {
        "id": t.id, "transfer_ref": t.transfer_ref, "product_id": t.product_id,
        "from_warehouse_id": t.from_warehouse_id, "to_warehouse_id": t.to_warehouse_id,
        "qty": round(float(t.qty), 2), "transit_days": t.transit_days, "status": t.status,
        "reason": t.reason, "short_orders": t.short_orders,
        "earliest_due": t.earliest_due.isoformat() if t.earliest_due else None,
        "eta": t.eta.isoformat() if t.eta else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "approved_by": t.approved_by, "approved_at": t.approved_at.isoformat() if t.approved_at else None,
        "received_by": t.received_by, "received_at": t.received_at.isoformat() if t.received_at else None,
        "cancelled_by": t.cancelled_by, "cancel_reason": t.cancel_reason,
        "overdue": bool(t.status == TRANSFER_IN_TRANSIT and t.eta and t.eta < datetime.now()),
    }


async def listing(db: AsyncSession, warehouse_id: str | None = None, status: str | None = None) -> list[dict]:
    """A planner scoped to one warehouse sees transfers that touch it, either as donor or as destination."""
    q = select(StockTransfer).order_by(StockTransfer.created_at.desc(), StockTransfer.id.desc())
    if status:
        q = q.where(StockTransfer.status == status.upper())
    rows = list((await db.execute(q.limit(500))).scalars())
    if warehouse_id:
        rows = [t for t in rows
                if warehouse_id in (t.from_warehouse_id, t.to_warehouse_id)]
    return [view(t) for t in rows]


async def summary(db: AsyncSession, warehouse_id: str | None = None) -> dict:
    rows = await listing(db, warehouse_id)
    proposed = [t for t in rows if t["status"] == TRANSFER_PROPOSED]
    transit = [t for t in rows if t["status"] == TRANSFER_IN_TRANSIT]
    return {
        "proposed": len(proposed), "proposed_units": round(sum(t["qty"] for t in proposed), 2),
        "in_transit": len(transit), "in_transit_units": round(sum(t["qty"] for t in transit), 2),
        "overdue": len([t for t in transit if t["overdue"]]),
        "enabled": settings.propose_transfers,
    }


async def _get(db: AsyncSession, transfer_id: int, warehouse_id: str | None) -> StockTransfer:
    t = await db.get(StockTransfer, transfer_id)
    if t is None:
        raise NotFoundError("Transfer not found")
    if warehouse_id and warehouse_id not in (t.from_warehouse_id, t.to_warehouse_id):
        raise NotFoundError("Transfer not found")
    return t


# ----------------------------------------------------------------- the moves
async def approve(db: AsyncSession, transfer_id: int, user: str, warehouse_id: str | None = None) -> dict:
    """Send the goods. The donor's stock drops now, because that is when they leave the shelf.

    The spare stock is checked again here, not trusted from when the proposal was raised: the plan may have
    been rebuilt since, or another transfer approved out of the same shelf.
    """
    t = await _get(db, transfer_id, warehouse_id)
    if t.status != TRANSFER_PROPOSED:
        raise BadRequestError(f"This transfer is {t.status.lower().replace('_', ' ')}, so it cannot be approved")
    available = await spare_now(db, int(t.product_id), t.from_warehouse_id)
    if available + 1e-6 < float(t.qty):
        raise BadRequestError(
            f"{t.from_warehouse_id} can only spare {round(available, 2):g} units of SKU {t.product_id} now, "
            f"not {round(float(t.qty), 2):g}. Recalculate the plan to raise a proposal that fits."
        )
    t.status = TRANSFER_IN_TRANSIT
    t.approved_by, t.approved_at = user, datetime.now()
    t.eta = datetime.now() + timedelta(days=int(t.transit_days))
    await db.commit()
    await stockview.apply_delta(db, {(int(t.product_id), t.from_warehouse_id): -float(t.qty)}, "transfer")
    await _replan(db, "transfer_approved")
    await db.refresh(t)
    return view(t)


async def receive(db: AsyncSession, transfer_id: int, user: str, warehouse_id: str | None = None) -> dict:
    """The goods arrived. The destination's stock rises, so the shortage that raised this can now be filled."""
    t = await _get(db, transfer_id, warehouse_id)
    if t.status != TRANSFER_IN_TRANSIT:
        raise BadRequestError("Only a transfer that is in transit can be received")
    t.status = TRANSFER_RECEIVED
    t.received_by, t.received_at = user, datetime.now()
    await db.commit()
    await stockview.apply_delta(db, {(int(t.product_id), t.to_warehouse_id): float(t.qty)}, "transfer")
    await _replan(db, "transfer_received")
    await db.refresh(t)
    return view(t)


async def cancel(db: AsyncSession, transfer_id: int, user: str, reason: str = "",
                 warehouse_id: str | None = None) -> dict:
    """Drop a proposal, or turn a shipment back. Goods already sent go back on the donor's shelf."""
    t = await _get(db, transfer_id, warehouse_id)
    if t.status not in OPEN_STATUSES:
        raise BadRequestError("Only a proposed or in-transit transfer can be cancelled")
    was_sent = t.status == TRANSFER_IN_TRANSIT
    t.status = TRANSFER_CANCELLED
    t.cancelled_by, t.cancel_reason = user, reason.strip()
    await db.commit()
    if was_sent:
        await stockview.apply_delta(db, {(int(t.product_id), t.from_warehouse_id): float(t.qty)}, "transfer")
        await _replan(db, "transfer_cancelled")
    await db.refresh(t)
    return view(t)


async def spare_now(db: AsyncSession, product_id: int, warehouse_id: str) -> float:
    """Units this warehouse could give away right now, by the same rule the proposals use."""
    from app.modules.dispatch import service as dispatch_service

    plan = await dispatch_service.current_plan(db)
    stock = await asyncio.to_thread(runtime.stock_snapshot)
    plan_df = await _plan_frame(db, plan)
    free = engine.free_stock(plan_df, stock, await held(db))
    demand = await asyncio.to_thread(daily_demand)
    key = (int(product_id), warehouse_id)
    return max(free.get(key, 0.0) - demand.get(key, 0.0) * settings.transfer_keep_days, 0.0)


async def _replan(db: AsyncSession, trigger: str) -> None:
    from app.modules.dispatch import service as dispatch_service
    await dispatch_service.recommend_plan(db, trigger=trigger)


# ----------------------------------------------------------------- lanes
async def list_lanes(db: AsyncSession) -> dict:
    rows = (await db.execute(select(TransferLane).order_by(
        TransferLane.from_warehouse_id, TransferLane.to_warehouse_id))).scalars().all()
    return {
        "default_days": settings.default_transfer_days,
        "lanes": [{"from_warehouse_id": r.from_warehouse_id, "to_warehouse_id": r.to_warehouse_id,
                   "transit_days": r.transit_days, "updated_by": r.updated_by,
                   "updated_at": r.updated_at.isoformat() if r.updated_at else None} for r in rows],
    }


def known_warehouses() -> set[str]:
    try:
        return set(runtime.stock_snapshot()["warehouse_id"].unique())
    except Exception:
        return set()


async def set_lane(db: AsyncSession, source: str, dest: str, days: int, user: str) -> dict:
    if source == dest:
        raise BadRequestError("A lane needs two different warehouses")
    if days < 0 or days > MAX_TRANSIT_DAYS:
        raise BadRequestError(f"Transit time must be between 0 and {MAX_TRANSIT_DAYS} days")
    known = known_warehouses()
    unknown = {w for w in (source, dest) if known and w not in known}
    if unknown:
        raise BadRequestError(f"Unknown warehouse(s): {sorted(unknown)}")
    row = await db.get(TransferLane, (source, dest))
    if row is None:
        row = TransferLane(from_warehouse_id=source, to_warehouse_id=dest)
        db.add(row)
    row.transit_days, row.updated_by, row.updated_at = days, user, datetime.now()
    await db.commit()
    return {"from_warehouse_id": source, "to_warehouse_id": dest, "transit_days": days}


async def clear_lane(db: AsyncSession, source: str, dest: str) -> None:
    row = await db.get(TransferLane, (source, dest))
    if row is None:
        raise NotFoundError("That lane has no transit time of its own")
    await db.delete(row)
    await db.commit()
