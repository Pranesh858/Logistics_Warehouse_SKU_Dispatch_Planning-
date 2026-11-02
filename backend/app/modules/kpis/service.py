"""Service-level and fill-rate KPIs, worked out from the tables that already hold the facts.

    fill rate         units planned / units ordered, on the current plan (after planner overrides)
    order fill rate   orders fully planned / orders on the current plan
    on-time share     shipped by the due date / shipped, from the ledger. The time used is when the WMS confirmed the
                      shipment, as the time the truck really left is not reported to us
    stock-outs        lines of the current plan with nothing to give (BACKORDERED)
    service level     the fill rate against SERVICE_LEVEL_TARGET_PCT
"""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch.models import LedgerEntry, Plan, PlanLine

TREND_DAYS = 30


def pct(part: float, whole: float) -> float | None:
    """None when there is nothing to measure: 0% would read as a failure that did not happen."""
    return round(part / whole * 100, 1) if whole else None


def summarise(rows: list[dict]) -> dict:
    """Rows hold qty_ordered, planned, status and at_risk. Also used by the scenario tool, so both agree."""
    ordered = sum(r["qty_ordered"] for r in rows)
    planned = sum(r["planned"] for r in rows)
    full = sum(1 for r in rows if r["planned"] >= r["qty_ordered"] - 1e-6)

    def count(status: str) -> int:
        return sum(1 for r in rows if r["status"] == status)

    return {
        "orders": len(rows), "orders_fully_planned": full,
        "units_ordered": round(ordered, 2), "units_planned": round(planned, 2),
        "fill_rate_pct": pct(planned, ordered), "order_fill_rate_pct": pct(full, len(rows)),
        "partial": count("PARTIAL"), "held": count("HELD"), "backordered": count("BACKORDERED"), "blocked": count("BLOCKED"),
        "at_risk": sum(1 for r in rows if r["at_risk"]),
    }


def service_level(fill_rate: float | None) -> dict:
    target = settings.service_level_target_pct
    return {"target_pct": target, "measure": "fill_rate", "value_pct": fill_rate,
            "met": None if fill_rate is None else fill_rate >= target}


def _bounds(date_from: dt.date | None, date_to: dt.date | None) -> tuple[dt.datetime | None, dt.datetime | None]:
    """From the start of the first day up to, not including, the day after the last."""
    return (dt.datetime.combine(date_from, dt.time.min) if date_from else None,
            dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min) if date_to else None)


def _in_range(q, column, start, end):
    if start is not None:
        q = q.where(column >= start)
    if end is not None:
        q = q.where(column < end)
    return q


async def _current_rows(db: AsyncSession, plan: Plan | None, warehouse_id, start, end) -> list[dict]:
    if plan is None:
        return []
    q = _in_range(select(PlanLine).where(PlanLine.plan_id == plan.id), PlanLine.order_timestamp, start, end)
    if warehouse_id:
        q = q.where(PlanLine.warehouse_id == warehouse_id)
    return [{"qty_ordered": l.qty_ordered, "status": l.status, "at_risk": l.at_risk,
             "planned": l.qty_allocated if l.status == "COMMITTED" else dispatch_service._final_qty(l)}
            for l in (await db.execute(q)).scalars()]


async def _shipped(db: AsyncSession, warehouse_id, start, end) -> list[tuple[dt.datetime, bool]]:
    """(when confirmed, on time) per shipped order. An order is deleted when it ships; its plan line keeps the due date."""
    q = (select(LedgerEntry.closed_at, PlanLine.due_date)
         .join(PlanLine, (PlanLine.plan_id == LedgerEntry.plan_id) & (PlanLine.order_id == LedgerEntry.order_id))
         .where(LedgerEntry.fulfilment == "SHIPPED", LedgerEntry.closed_at.is_not(None)))
    q = _in_range(q, LedgerEntry.closed_at, start, end)
    if warehouse_id:
        q = q.where(LedgerEntry.warehouse_id == warehouse_id)
    return [(closed, closed <= due) for closed, due in (await db.execute(q)).all()]


async def _approved_fill(db: AsyncSession, warehouse_id, start, end) -> dict[dt.date, list[float]]:
    """Per day of approval: [units sent, units asked of those plans]. One planner's approval leaves the other warehouses
    of that plan for their own planners, so only warehouses that sent something in a plan count for it."""
    q = _in_range(select(Plan).where(Plan.approved_at.is_not(None)), Plan.approved_at, start, end)
    out: dict[dt.date, list[float]] = {}
    for plan in (await db.execute(q)).scalars().all():
        sent_q = select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)
        if warehouse_id:
            sent_q = sent_q.where(LedgerEntry.warehouse_id == warehouse_id)
        sent = (await db.execute(sent_q)).scalars().all()
        if not sent:
            continue
        lines = (await db.execute(select(PlanLine).where(
            PlanLine.plan_id == plan.id, PlanLine.status != "COMMITTED",
            PlanLine.warehouse_id.in_({e.warehouse_id for e in sent})))).scalars().all()
        day = out.setdefault(plan.approved_at.date(), [0.0, 0.0])
        day[0] += sum(e.qty_committed for e in sent)
        day[1] += sum(l.qty_ordered for l in lines)
    return out


async def _trend(db: AsyncSession, warehouse_id, start, end, shipped: list[tuple[dt.datetime, bool]]) -> list[dict]:
    """One row per day something was approved or shipped. A day with neither has nothing to report."""
    fill = await _approved_fill(db, warehouse_id, start, end)
    ship: dict[dt.date, list[int]] = {}
    for closed, on_time in shipped:
        day = ship.setdefault(closed.date(), [0, 0])
        day[0] += 1
        day[1] += int(on_time)
    return [{"date": d.isoformat(),
             "fill_rate_pct": pct(*fill[d]) if d in fill else None,
             "on_time_pct": pct(ship[d][1], ship[d][0]) if d in ship else None,
             "shipped": ship[d][0] if d in ship else 0}
            for d in sorted({*fill, *ship})]


async def compute(db: AsyncSession, warehouse_id: str | None = None, date_from: dt.date | None = None,
                  date_to: dt.date | None = None) -> dict:
    """The date range applies to when an order was placed (plan figures) and when it was shipped or approved (on-time
    share and trend). Without dates the plan figures cover the whole current plan and the trend the last 30 days."""
    start, end = _bounds(date_from, date_to)
    plan = await dispatch_service.current_plan(db)
    now = summarise(await _current_rows(db, plan, warehouse_id, start, end))
    shipped = await _shipped(db, warehouse_id, start, end)
    on_time = sum(1 for _, ok in shipped if ok)

    trend_start, trend_shipped = start, shipped
    if start is None and end is None:
        trend_start = dt.datetime.combine(dt.date.today() - dt.timedelta(days=TREND_DAYS - 1), dt.time.min)
        trend_shipped = await _shipped(db, warehouse_id, trend_start, None)
    return {
        "warehouse_id": warehouse_id, "date_from": date_from, "date_to": date_to,
        "plan_version": plan.version if plan else None, **now,
        "stock_outs": now["backordered"], "shipped": len(shipped), "shipped_on_time": on_time,
        "on_time_pct": pct(on_time, len(shipped)), "service_level": service_level(now["fill_rate_pct"]),
        "trend": await _trend(db, warehouse_id, trend_start, end, trend_shipped),
    }
