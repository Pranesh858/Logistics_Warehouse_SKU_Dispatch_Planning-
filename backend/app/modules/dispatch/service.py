"""
Dispatch planning workflow:

    orders arrive / startup  ->  engine builds a RECOMMENDED plan (no one is asked)
    the units to dispatch are packed into the configured trucks (several trucks per plan)
    planner reviews (optional overrides, reason mandatory; can also move an order to another truck)
    planner approves         ->  approved lines go to the WMS automatically, stock is reserved in the ledger
    stuck exports            ->  retry; nothing is ever sent to the WMS before approval
"""
import asyncio
import contextlib
import datetime as dt

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import locks
from app.core.config import settings
from app.modules.dispatch import engine, packing, transfers
from app.modules.dispatch.models import (
    PLAN_EXPORTED, PLAN_NOTHING, PLAN_PARTIAL, PLAN_RECOMMENDED, PLAN_SUPERSEDED,
    BlockedSku, ExportLog, LedgerEntry, Order, Plan, PlanLine, Truck, TruckLoad,
)
from app.modules.dispatch.schemas import OrderIn
from app.modules.dispatch.wms import get_wms_client
from app.modules.forecast import service as forecast_service
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError, ConflictError, NotFoundError



def _lock() -> asyncio.Lock:
    """One plan write / WMS export at a time -> no double export, no double allocation."""
    return locks.named("plan")


# ----------------------------------------------------------------- helpers
def _final_qty(line: PlanLine) -> float:
    """Units that go to the WMS if the planner approves right now."""
    if line.status == "COMMITTED":
        return 0.0
    if line.decision == "REJECTED":
        return 0.0
    if line.decision == "OVERRIDDEN" and line.override_qty is not None:
        return float(line.override_qty)
    return float(line.qty_allocated)


async def _stock() -> pd.DataFrame:
    return await asyncio.to_thread(runtime.stock_snapshot)


async def _ledger_df(db: AsyncSession) -> pd.DataFrame:
    rows = (await db.execute(select(LedgerEntry))).scalars().all()
    return pd.DataFrame(
        [dict(order_id=r.order_id, product_id=r.product_id, warehouse_id=r.warehouse_id, qty_committed=r.qty_committed,
              qty_reserved=r.qty_committed if r.fulfilment == "RESERVED" else 0.0)
         for r in rows],
        columns=["order_id", "product_id", "warehouse_id", "qty_committed", "qty_reserved"],
    )


async def _check_stock(db: AsyncSession, lines: list[PlanLine]) -> None:
    """Hard invariant: committed + about-to-send units never exceed the shelf, per SKU x warehouse."""
    stock = {(r.product_id, r.warehouse_id): r.stock_on_hand for r in (await _stock()).itertuples()}
    ledger = await _ledger_df(db)
    used = ledger.groupby(["product_id", "warehouse_id"])["qty_reserved"].sum().to_dict() if len(ledger) else {}
    new: dict = {}
    for ln in lines:
        new[(ln.product_id, ln.warehouse_id)] = new.get((ln.product_id, ln.warehouse_id), 0.0) + _final_qty(ln)
    for key, qty in new.items():
        if used.get(key, 0.0) + qty > stock.get(key, 0.0) + 1e-6:
            raise BadRequestError(
                f"SKU {key[0]} at {key[1]}: {qty:g} to dispatch + {used.get(key, 0.0):g} already committed "
                f"exceeds {stock.get(key, 0.0):g} on hand"
            )


# ----------------------------------------------------------------- orders
def _order_row(o: OrderIn) -> Order:
    return Order(**o.model_dump())


async def seed_orders(db: AsyncSession) -> int:
    from pathlib import Path
    path = Path(settings.seed_orders_path)
    if not settings.seed_orders_on_startup or not path.exists():
        return 0
    if (await db.execute(select(func.count()).select_from(Order))).scalar_one():
        return 0
    df = pd.read_csv(path, parse_dates=["order_timestamp", "due_date"])
    df["order_timestamp"] = df["order_timestamp"].dt.floor("s")
    df["due_date"] = df["due_date"].dt.floor("s")
    # The file holds fixed dates, which would be long past by the time anyone runs the demo. Move every order by
    # the same amount so the newest one arrives now: order times and due windows keep their spacing.
    shift = pd.Timestamp.now().floor("s") - df["order_timestamp"].max()
    df["order_timestamp"] += shift
    df["due_date"] += shift
    db.add_all(Order(**{k: (v.to_pydatetime() if hasattr(v, "to_pydatetime") else v) for k, v in rec.items()
                        if k in Order.__table__.columns.keys()})
               for rec in df.to_dict(orient="records"))
    await db.commit()
    return len(df)


async def ingest_orders(db: AsyncSession, orders: list[OrderIn]) -> Plan:
    df = pd.DataFrame([o.model_dump() for o in orders])
    stock = await _stock()
    try:
        engine.validate_orders(df, set(stock["product_id"]), set(stock["warehouse_id"]))
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    existing = set((await db.execute(select(Order.order_id).where(Order.order_id.in_(list(df["order_id"]))))).scalars())
    if existing:
        raise ConflictError(f"order_id(s) already exist: {sorted(existing)[:10]}")
    db.add_all(_order_row(o) for o in orders)
    await db.commit()
    return await recommend_plan(db, trigger="new_orders")


# ----------------------------------------------------------------- recommend
async def recommend_plan(db: AsyncSession, trigger: str = "recalculate", carry_from: Plan | None = None,
                         carry_except: str | None = None) -> Plan | None:
    """carry_from: a plan that was just approved for one warehouse; the planner's edits on every OTHER warehouse are kept."""
    async with _lock():
        return await _recommend_locked(db, trigger, carry_from, carry_except)


async def _recommend_locked(db: AsyncSession, trigger: str, carry_from: Plan | None = None,
                            carry_except: str | None = None) -> Plan | None:
    rows = (await db.execute(select(Order))).scalars().all()
    if not rows:
        return None
    orders = pd.DataFrame([{c.name: getattr(r, c.name) for c in Order.__table__.columns} for r in rows])
    for c in ("order_timestamp", "due_date"):
        orders[c] = pd.to_datetime(orders[c])
    stock = await _stock()
    blocked = {(b.product_id, b.warehouse_id) for b in (await db.execute(select(BlockedSku))).scalars()}
    ledger = await _ledger_df(db)

    plan_df = await asyncio.to_thread(engine.allocate, orders, stock, None, blocked, ledger)
    bad = engine.verify_no_overallocation(plan_df, stock)
    if len(bad):
        raise RuntimeError(f"OVER-ALLOCATION detected for {len(bad)} SKU x warehouse pair(s); plan discarded")
    plan_df = engine.assign_waves(plan_df, settings.wave_capacity)

    # carry planner overrides from the draft being replaced
    old_draft = (await db.execute(
        select(Plan).where(Plan.status == PLAN_RECOMMENDED).order_by(Plan.version.desc()))).scalars().first()
    carried: dict[str, PlanLine] = {}
    manual_trucks: dict[str, int] = {}
    source = old_draft or carry_from
    if source is not None:
        old_lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == source.id))).scalars().all()
        keep_ids = {ln.order_id for ln in old_lines if carry_except is None or ln.warehouse_id != carry_except}
        manual_trucks = {t.order_id: t.truck_id for t in (await db.execute(
            select(TruckLoad).where(TruckLoad.plan_id == source.id, TruckLoad.manual.is_(True)))).scalars()
            if t.order_id in keep_ids}
        carried = {ln.order_id: ln for ln in old_lines if ln.decision in ("OVERRIDDEN", "REJECTED") and ln.order_id in keep_ids}
    if old_draft is not None:
        old_draft.status = PLAN_SUPERSEDED

    version = ((await db.execute(select(func.max(Plan.version)))).scalar() or 0) + 1
    plan = Plan(version=version, status=PLAN_RECOMMENDED, trigger=trigger, wave_capacity=settings.wave_capacity)
    for r in plan_df.itertuples():
        line = PlanLine(
            order_id=r.order_id, order_timestamp=r.order_timestamp.to_pydatetime(), customer_id=r.customer_id,
            customer_tier=r.customer_tier, product_id=int(r.product_id), warehouse_id=r.warehouse_id, city=r.city,
            due_date=r.due_date.to_pydatetime(), wave_id=r.wave_id, qty_ordered=float(r.qty_ordered),
            qty_allocated=float(r.qty_allocated), qty_short=float(r.qty_short), status=r.status,
            at_risk=bool(r.at_risk), rules_applied=r.rules_applied,
            exception_type=engine.exception_type(r.status, bool(r.at_risk)),
        )
        prev = carried.get(r.order_id)
        if prev is not None and r.status != "COMMITTED":
            keep = prev.decision == "REJECTED" or (prev.override_qty or 0) <= r.qty_ordered
            if keep:
                line.decision, line.override_qty, line.override_reason = prev.decision, prev.override_qty, prev.override_reason
        plan.lines.append(line)
    db.add(plan)
    await db.flush()
    await _repack(db, plan, manual_trucks)
    await db.commit()
    await db.refresh(plan)
    # Shortages this plan reports may be coverable from another warehouse. Proposals only; nothing moves
    # until a planner approves one, and a failure here must not cost us the plan.
    try:
        await transfers.refresh_proposals(db, plan)
    except Exception as exc:                 # noqa: BLE001
        print(f"[transfers] could not refresh proposals: {exc}", flush=True)
    return plan


# ----------------------------------------------------------------- trucks
async def _active_trucks(db: AsyncSession) -> list[Truck]:
    return list((await db.execute(select(Truck).where(Truck.active.is_(True)).order_by(Truck.id))).scalars())


async def _repack(db: AsyncSession, plan: Plan, manual: dict[str, int] | None = None) -> None:
    """Rebuild the truck loads of a RECOMMENDED plan from the units that would be dispatched right now."""
    lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan.id))).scalars().all()
    if manual is None:
        manual = {t.order_id: t.truck_id for t in (await db.execute(
            select(TruckLoad).where(TruckLoad.plan_id == plan.id, TruckLoad.manual.is_(True)))).scalars()}
    await db.execute(delete(TruckLoad).where(TruckLoad.plan_id == plan.id))
    trucks = [dict(id=t.id, warehouse_id=t.warehouse_id, capacity=t.capacity_units) for t in await _active_trucks(db)]
    items = [dict(order_id=l.order_id, warehouse_id=l.warehouse_id, qty=_final_qty(l), tier=l.customer_tier,
                  due_date=l.due_date, order_timestamp=l.order_timestamp, manual_truck_id=manual.get(l.order_id))
             for l in lines if _final_qty(l) > 0]
    for ld in packing.pack(trucks, items):
        db.add(TruckLoad(plan_id=plan.id, **ld))
    await db.flush()


async def _repack_current(db: AsyncSession) -> None:
    plan = (await db.execute(select(Plan).where(Plan.status == PLAN_RECOMMENDED).order_by(Plan.version.desc()))).scalars().first()
    if plan is not None:
        await _repack(db, plan)


async def seed_default_trucks(db: AsyncSession) -> int:
    """First start: give every warehouse a few sample trucks so the plan can be loaded. The planner edits them freely."""
    if not settings.seed_trucks_on_startup:
        return 0
    if (await db.execute(select(func.count()).select_from(Truck))).scalar_one():
        return 0
    warehouses = sorted(set((await _stock())["warehouse_id"]))
    n = max(1, settings.default_trucks_per_warehouse)
    for wh in warehouses:
        for i in range(1, n + 1):
            db.add(Truck(name=f"{wh}-T{i}", warehouse_id=wh, capacity_units=settings.default_truck_capacity))
    await db.commit()
    return len(warehouses) * n


async def list_trucks(db: AsyncSession, include_inactive: bool = False, warehouse_id: str | None = None) -> list[Truck]:
    q = select(Truck).order_by(Truck.warehouse_id, Truck.id)
    if not include_inactive:
        q = q.where(Truck.active.is_(True))
    if warehouse_id:
        q = q.where(Truck.warehouse_id == warehouse_id)
    return list((await db.execute(q)).scalars())


async def truck_warehouse(db: AsyncSession, truck_id: int) -> str:
    truck = await db.get(Truck, truck_id)
    if truck is None:
        raise NotFoundError("Truck not found")
    return truck.warehouse_id


async def line_warehouse(db: AsyncSession, plan_id: int, order_id: str) -> str:
    wh = (await db.execute(select(PlanLine.warehouse_id).where(PlanLine.plan_id == plan_id, PlanLine.order_id == order_id))).scalars().first()
    if wh is None:
        raise NotFoundError("Order not in this plan")
    return wh


async def _name_taken(db: AsyncSession, name: str, except_id: int | None = None) -> bool:
    rows = (await db.execute(select(Truck).where(Truck.active.is_(True)))).scalars()
    return any(t.name.strip().lower() == name.strip().lower() and t.id != except_id for t in rows)


async def create_truck(db: AsyncSession, name: str, warehouse_id: str, capacity_units: float) -> Truck:
    async with _lock():
        if not name.strip():
            raise BadRequestError("Truck name is required")
        if capacity_units <= 0:
            raise BadRequestError("Truck capacity must be above 0")
        if warehouse_id not in set((await _stock())["warehouse_id"]):
            raise BadRequestError(f"Unknown warehouse {warehouse_id}")
        if await _name_taken(db, name):
            raise ConflictError("A truck with this name already exists")
        truck = Truck(name=name.strip(), warehouse_id=warehouse_id, capacity_units=capacity_units)
        db.add(truck)
        await db.flush()
        await _repack_current(db)
        await db.commit()
        await db.refresh(truck)
        return truck


async def update_truck(db: AsyncSession, truck_id: int, name: str | None, capacity_units: float | None,
                       active: bool | None) -> Truck:
    async with _lock():
        truck = await db.get(Truck, truck_id)
        if truck is None:
            raise NotFoundError("Truck not found")
        if name is not None:
            if not name.strip():
                raise BadRequestError("Truck name is required")
            if await _name_taken(db, name, except_id=truck.id):
                raise ConflictError("A truck with this name already exists")
            truck.name = name.strip()
        if capacity_units is not None:
            if capacity_units <= 0:
                raise BadRequestError("Truck capacity must be above 0")
            truck.capacity_units = capacity_units
        if active is not None:
            truck.active = active
        await db.flush()
        await _repack_current(db)
        await db.commit()
        await db.refresh(truck)
        return truck


async def remove_truck(db: AsyncSession, truck_id: int) -> Truck:
    return await update_truck(db, truck_id, None, None, False)


async def move_order_to_truck(db: AsyncSession, plan_id: int, order_id: str, truck_id: int | None) -> Plan:
    """Planner puts a whole order on a chosen truck (or passes None to let the packer decide again)."""
    async with _lock():
        plan = await get_plan(db, plan_id)
        if plan.status != PLAN_RECOMMENDED:
            raise ConflictError(f"Plan v{plan.version} is {plan.status}; only the current recommendation can be edited")
        line = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan_id, PlanLine.order_id == order_id))).scalars().first()
        if line is None:
            raise NotFoundError("Order not in this plan")
        qty = _final_qty(line)
        manual = {t.order_id: t.truck_id for t in (await db.execute(
            select(TruckLoad).where(TruckLoad.plan_id == plan_id, TruckLoad.manual.is_(True)))).scalars()}
        if truck_id is None:
            manual.pop(order_id, None)
        else:
            if qty <= 0:
                raise BadRequestError("This order has nothing to dispatch, so it cannot be put on a truck")
            truck = await db.get(Truck, truck_id)
            if truck is None or not truck.active:
                raise NotFoundError("Truck not found")
            if truck.warehouse_id != line.warehouse_id:
                raise BadRequestError(f"{truck.name} loads from {truck.warehouse_id}, but this order ships from {line.warehouse_id}")
            used = sum(t.qty for t in (await db.execute(select(TruckLoad).where(
                TruckLoad.plan_id == plan_id, TruckLoad.truck_id == truck_id, TruckLoad.manual.is_(True),
                TruckLoad.order_id != order_id))).scalars())
            if used + qty > truck.capacity_units + 1e-6:
                raise BadRequestError(
                    f"{truck.name} cannot take {qty:g} units: only {max(truck.capacity_units - used, 0):g} of "
                    f"{truck.capacity_units:g} left for manual loads")
            manual[order_id] = truck_id
        await _repack(db, plan, manual)
        await db.commit()
        return plan


# ----------------------------------------------------------------- read
async def get_plan(db: AsyncSession, plan_id: int) -> Plan:
    plan = await db.get(Plan, plan_id)
    if plan is None:
        raise NotFoundError("Plan not found")
    return plan


async def current_plan(db: AsyncSession) -> Plan | None:
    plan = (await db.execute(select(Plan).where(Plan.status == PLAN_RECOMMENDED).order_by(Plan.version.desc()))).scalars().first()
    if plan is None:
        plan = (await db.execute(select(Plan).order_by(Plan.version.desc()))).scalars().first()
    return plan


async def list_plans(db: AsyncSession) -> list[Plan]:
    return list((await db.execute(select(Plan).order_by(Plan.version.desc()))).scalars())


async def plan_view(db: AsyncSession, plan: Plan, warehouse_id: str | None = None) -> dict:
    """warehouse_id limits the view to one warehouse (what a planner is allowed to see)."""
    lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan.id))).scalars().all()
    ledger = {e.order_id: e for e in (await db.execute(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id))).scalars()}
    last_err: dict[str, str | None] = {}
    for lg in (await db.execute(select(ExportLog).where(ExportLog.plan_id == plan.id).order_by(ExportLog.id))).scalars():
        last_err[lg.order_id] = lg.error
    conflicts = {lg.order_id for lg in (await db.execute(
        select(ExportLog).where(ExportLog.plan_id == plan.id, ExportLog.export_status == "CONFLICT"))).scalars()}
    loads = (await db.execute(select(TruckLoad).where(TruckLoad.plan_id == plan.id))).scalars().all()
    truck_rows = {t.id: t for t in (await db.execute(select(Truck))).scalars()}
    by_order: dict[str, list[TruckLoad]] = {}
    for ld in loads:
        by_order.setdefault(ld.order_id, []).append(ld)
    out = []
    for ln in sorted(lines, key=lambda x: (x.product_id, x.warehouse_id, x.customer_tier != "Premium", x.due_date)):
        d = {c.name: getattr(ln, c.name) for c in PlanLine.__table__.columns}
        d["final_qty"] = _final_qty(ln) if plan.status == PLAN_RECOMMENDED else (ledger[ln.order_id].qty_committed if ln.order_id in ledger else 0.0)
        ent = ledger.get(ln.order_id)
        d["export_status"] = "CONFLICT" if ln.order_id in conflicts else (ent.wms_status if ent else None)
        d["export_error"] = last_err.get(ln.order_id) if d["export_status"] in ("FAILED", "CONFLICT") else None
        mine = by_order.get(ln.order_id, [])
        d["truck_assignments"] = [{"truck_id": m.truck_id, "truck_name": truck_rows[m.truck_id].name if m.truck_id in truck_rows else f"#{m.truck_id}",
                                   "qty": m.qty, "manual": m.manual} for m in mine]
        if plan.status == PLAN_RECOMMENDED:
            d["send_qty"] = round(sum(m.qty for m in mine), 6)
        else:
            d["send_qty"] = ledger[ln.order_id].qty_committed if ln.order_id in ledger else 0.0
        out.append(d)
    trucks_out, unassigned = _truck_view(plan, loads, truck_rows, out, await _active_trucks(db))
    if warehouse_id:
        out = [l for l in out if l["warehouse_id"] == warehouse_id]
        trucks_out = [t for t in trucks_out if t["warehouse_id"] == warehouse_id]
        unassigned = [u for u in unassigned if u["warehouse_id"] == warehouse_id]
    return {
        "id": plan.id, "version": plan.version, "status": plan.status, "trigger": plan.trigger,
        "created_at": plan.created_at, "approved_by": plan.approved_by, "approved_at": plan.approved_at,
        "summary": _summary(out), "lines": out, "trucks": trucks_out, "unassigned": unassigned,
    }


def _truck_view(plan: Plan, loads: list[TruckLoad], truck_rows: dict, lines: list[dict], active: list[Truck]):
    line_by_id = {l["order_id"]: l for l in lines}
    shown = list(active) if plan.status == PLAN_RECOMMENDED else []
    seen = {t.id for t in shown}
    for ld in loads:                                   # history: trucks used by an older plan stay visible
        if ld.truck_id not in seen and ld.truck_id in truck_rows:
            shown.append(truck_rows[ld.truck_id])
            seen.add(ld.truck_id)
    trucks = []
    for t in sorted(shown, key=lambda x: (x.warehouse_id, x.id)):
        mine = [ld for ld in loads if ld.truck_id == t.id]
        loaded = round(sum(ld.qty for ld in mine), 6)
        trucks.append({
            "id": t.id, "name": t.name, "warehouse_id": t.warehouse_id, "capacity_units": t.capacity_units,
            "active": t.active, "loaded_units": loaded, "free_units": round(max(t.capacity_units - loaded, 0.0), 6),
            "fill_pct": round(loaded / t.capacity_units * 100, 1) if t.capacity_units else 0.0,
            "orders": [{"order_id": ld.order_id, "qty": ld.qty, "manual": ld.manual,
                        "customer_tier": line_by_id.get(ld.order_id, {}).get("customer_tier"),
                        "due_date": line_by_id.get(ld.order_id, {}).get("due_date")} for ld in mine],
        })
    unassigned = []
    if plan.status == PLAN_RECOMMENDED:
        for l in lines:
            left = round(l["final_qty"] - l["send_qty"], 6)
            if left > 1e-6:
                unassigned.append({"order_id": l["order_id"], "warehouse_id": l["warehouse_id"], "product_id": l["product_id"],
                                   "customer_tier": l["customer_tier"], "due_date": l["due_date"], "qty": left})
    return trucks, unassigned


def _summary(lines: list[dict]) -> dict:
    ordered = sum(l["qty_ordered"] for l in lines)
    alloc = sum(l["qty_allocated"] for l in lines)
    by_status: dict[str, int] = {}
    by_tier: dict[str, dict] = {}
    for l in lines:
        by_status[l["status"]] = by_status.get(l["status"], 0) + 1
        t = by_tier.setdefault(l["customer_tier"], {"ordered": 0.0, "allocated": 0.0})
        t["ordered"] += l["qty_ordered"]
        t["allocated"] += l["qty_allocated"]
    return {
        "orders": len(lines),
        "units_ordered": round(ordered, 2),
        "units_allocated": round(alloc, 2),
        "coverage_pct": round(alloc / ordered * 100, 1) if ordered else 0.0,
        "units_to_send": round(sum(l["send_qty"] for l in lines), 2),
        "orders_to_send": sum(1 for l in lines if l["send_qty"] > 0),
        "units_dispatchable": round(sum(l["final_qty"] for l in lines), 2),
        "trucks_used": len({a["truck_id"] for l in lines for a in l["truck_assignments"]}),
        "unassigned_orders": sum(1 for l in lines if l["final_qty"] - l["send_qty"] > 1e-6),
        "exceptions": sum(1 for l in lines if l["exception_type"]),
        "at_risk": sum(1 for l in lines if l["at_risk"]),
        "overridden": sum(1 for l in lines if l["decision"] == "OVERRIDDEN"),
        "rejected": sum(1 for l in lines if l["decision"] == "REJECTED"),
        "failed_exports": sum(1 for l in lines if l["export_status"] == "FAILED"),
        "by_status": by_status,
        "by_tier": {k: {**v, "coverage_pct": round(v["allocated"] / v["ordered"] * 100, 1) if v["ordered"] else 0.0}
                    for k, v in by_tier.items()},
    }


# ----------------------------------------------------------------- review
async def review_line(db: AsyncSession, plan_id: int, order_id: str, decision: str,
                      override_qty: float | None, override_reason: str | None) -> Plan:
    async with _lock():
        plan = await get_plan(db, plan_id)
        if plan.status != PLAN_RECOMMENDED:
            raise ConflictError(f"Plan v{plan.version} is {plan.status}; only the current recommendation can be edited")
        lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan_id))).scalars().all()
        line = next((l for l in lines if l.order_id == order_id), None)
        if line is None:
            raise NotFoundError("Order not in this plan")
        if line.status == "COMMITTED":
            raise ConflictError("This order is already committed to the WMS and cannot be changed")

        old = (line.decision, line.override_qty, line.override_reason)
        if decision == "OVERRIDDEN":
            if override_qty is None:
                raise BadRequestError("override_qty is required when overriding")
            if not (override_reason or "").strip():
                raise BadRequestError("A reason is mandatory for every override")
            if override_qty > line.qty_ordered:
                raise BadRequestError(f"override_qty cannot exceed the ordered quantity ({line.qty_ordered:g})")
            line.decision, line.override_qty, line.override_reason = decision, override_qty, override_reason.strip()
        elif decision == "REJECTED":
            line.decision, line.override_qty, line.override_reason = decision, None, (override_reason or "").strip() or None
        else:
            line.decision, line.override_qty, line.override_reason = "APPROVED", None, None
        try:
            await _check_stock(db, list(lines))
        except BadRequestError:
            line.decision, line.override_qty, line.override_reason = old
            raise
        await db.flush()
        await _repack(db, plan)
        await db.commit()
        return plan


# ----------------------------------------------------------------- approve + export
async def approve_plan(db: AsyncSession, plan_id: int, approved_by: str, warehouse_id: str | None = None) -> Plan:
    """warehouse_id: approve only that warehouse's orders (a planner's approval). None = every warehouse (admin)."""
    async with _lock():
        plan = await get_plan(db, plan_id)
        if plan.status != PLAN_RECOMMENDED:
            raise ConflictError(f"Plan v{plan.version} is {plan.status}; it cannot be approved again")
        all_lines = (await db.execute(select(PlanLine).where(PlanLine.plan_id == plan_id))).scalars().all()
        lines = [l for l in all_lines if warehouse_id is None or l.warehouse_id == warehouse_id]
        if warehouse_id and not lines:
            raise NotFoundError(f"No orders for {warehouse_id} in this plan")
        missing = [l.order_id for l in lines if l.decision == "OVERRIDDEN" and not (l.override_reason or "").strip()]
        if missing:
            raise BadRequestError(f"Overridden orders without a reason: {missing[:10]}")
        await _check_stock(db, list(all_lines))
        await _repack(db, plan)                    # make sure the truck loads match the final quantities
        assigned: dict[str, float] = {}
        mine = {l.order_id for l in lines}
        for ld in (await db.execute(select(TruckLoad).where(TruckLoad.plan_id == plan.id))).scalars():
            if ld.order_id in mine:
                assigned[ld.order_id] = assigned.get(ld.order_id, 0.0) + ld.qty

        plan.approved_by, plan.approved_at = approved_by.strip(), dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        sendable = []
        for l in lines:
            if l.status == "COMMITTED":
                continue
            if l.decision is None:
                l.decision = "APPROVED"
            if assigned.get(l.order_id, 0.0) > 0:      # only what is on a truck goes to the WMS
                sendable.append(l)

        already = set((await db.execute(select(LedgerEntry.order_id))).scalars())
        for l in sendable:
            qty = assigned[l.order_id]
            if l.order_id in already:
                db.add(ExportLog(plan_id=plan.id, order_id=l.order_id, qty=qty, export_status="CONFLICT", attempts=0,
                                 error="Order already committed to the WMS earlier - not re-sent (possible duplicate)."))
                continue
            # reserve the stock first: from here on no newer plan can hand it to anyone else
            db.add(LedgerEntry(order_id=l.order_id, product_id=l.product_id, warehouse_id=l.warehouse_id,
                               qty_committed=qty, customer_tier=l.customer_tier, committed_decision=l.decision,
                               plan_id=plan.id, wms_status="FAILED"))
        # The reservations are kept before anything is sent, and the transaction is closed: the sends below are
        # network calls, and holding the database for their whole length blocked every other write (on SQLite the
        # whole database) for minutes with a large plan. Until every order is through, the plan reads as partly
        # sent, which is also what a retry needs if the export is interrupted.
        if sendable:
            plan.status = PLAN_PARTIAL
        await db.commit()
        await _send_pending(db, plan, warehouse_id)
        await _refresh_plan_status(db, plan, has_sendable=bool(sendable))
        await db.commit()
    # always leave the planners with an up-to-date recommendation for whatever is still open
    # (after one warehouse approves, the other warehouses keep their edits)
    await recommend_plan(db, trigger="after_approval", carry_from=plan if warehouse_id else None, carry_except=warehouse_id)
    await db.refresh(plan)
    return plan


EXPORT_COMMIT_EVERY = 25       # results are saved as they come, so an interrupted export loses at most this many


async def _send_pending(db: AsyncSession, plan: Plan, warehouse_id: str | None = None) -> None:
    """Send every order of this plan the WMS has not accepted yet.

    A WMS that is down or hanging is not tried order after order: once `wms_give_up_after` orders have failed in a
    row the rest are logged as not tried and left for a retry, so an approval against a dead WMS ends in seconds
    rather than taking (orders x retries x timeout).
    """
    client = get_wms_client()
    q = select(LedgerEntry).where(LedgerEntry.plan_id == plan.id, LedgerEntry.wms_status == "FAILED")
    if warehouse_id:
        q = q.where(LedgerEntry.warehouse_id == warehouse_id)
    pending = (await db.execute(q)).scalars().all()
    names = {t.id: t.name for t in (await db.execute(select(Truck))).scalars()}
    loads: dict[str, list] = {}
    for ld in (await db.execute(select(TruckLoad).where(TruckLoad.plan_id == plan.id))).scalars():
        loads.setdefault(ld.order_id, []).append(ld)
    session = client.session() if hasattr(client, "session") else contextlib.nullcontext(client)
    failed_in_a_row = 0
    async with session:
        for i, ent in enumerate(pending, start=1):
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            if failed_in_a_row >= settings.wms_give_up_after:
                db.add(ExportLog(plan_id=plan.id, order_id=ent.order_id, qty=ent.qty_committed, export_status="FAILED",
                                 attempts=0, error=f"not tried: the WMS failed {failed_in_a_row} orders in a row, "
                                                   f"so this one waits for a retry"))
                continue
            payload = {"order_id": ent.order_id, "product_id": ent.product_id, "warehouse_id": ent.warehouse_id,
                       "qty": ent.qty_committed, "customer_tier": ent.customer_tier, "plan_version": plan.version,
                       "approved_by": plan.approved_by,
                       "trucks": [{"truck_id": ld.truck_id, "truck_name": names.get(ld.truck_id), "qty": ld.qty}
                                  for ld in loads.get(ent.order_id, [])]}
            attempts, ok, err = 0, False, None
            while attempts < settings.wms_max_retries and not ok:
                attempts += 1
                ok, err = await client.send(payload, attempts)
            failed_in_a_row = 0 if ok else failed_in_a_row + 1
            ent.wms_status = "SENT" if ok else "FAILED"
            db.add(ExportLog(plan_id=plan.id, order_id=ent.order_id, qty=ent.qty_committed,
                             export_status="SUCCESS" if ok else "FAILED", attempts=attempts, error=None if ok else err,
                             exported_at=now if ok else None))
            if i % EXPORT_COMMIT_EVERY == 0:
                await db.commit()


async def _refresh_plan_status(db: AsyncSession, plan: Plan, has_sendable: bool | None = None) -> None:
    entries = (await db.execute(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id))).scalars().all()
    if not entries:
        plan.status = PLAN_NOTHING
    elif any(e.wms_status == "FAILED" for e in entries):
        plan.status = PLAN_PARTIAL
    else:
        plan.status = PLAN_EXPORTED


async def retry_exports(db: AsyncSession, plan_id: int, warehouse_id: str | None = None) -> Plan:
    async with _lock():
        plan = await get_plan(db, plan_id)
        if plan.status != PLAN_PARTIAL:
            raise ConflictError("Nothing to retry for this plan")
        await _send_pending(db, plan, warehouse_id)
        await _refresh_plan_status(db, plan)
        await db.commit()
        return plan


async def export_log(db: AsyncSession, plan_id: int, warehouse_id: str | None = None) -> list[ExportLog]:
    await get_plan(db, plan_id)
    logs = list((await db.execute(select(ExportLog).where(ExportLog.plan_id == plan_id).order_by(ExportLog.id))).scalars())
    if warehouse_id:
        mine = set((await db.execute(select(PlanLine.order_id).where(PlanLine.plan_id == plan_id, PlanLine.warehouse_id == warehouse_id))).scalars())
        logs = [l for l in logs if l.order_id in mine]
    return logs


# ----------------------------------------------------------------- blocked SKUs
async def list_blocked(db: AsyncSession, warehouse_id: str | None = None) -> list[BlockedSku]:
    q = select(BlockedSku)
    if warehouse_id:
        q = q.where(BlockedSku.warehouse_id == warehouse_id)
    return list((await db.execute(q)).scalars())


async def block_sku(db: AsyncSession, product_id: int, warehouse_id: str, reason: str) -> Plan | None:
    stock = await _stock()
    if not ((stock["product_id"] == product_id) & (stock["warehouse_id"] == warehouse_id)).any():
        raise BadRequestError("Unknown SKU / warehouse combination")
    exists = (await db.execute(select(BlockedSku).where(BlockedSku.product_id == product_id, BlockedSku.warehouse_id == warehouse_id))).scalars().first()
    if exists:
        raise ConflictError("Already blocked")
    db.add(BlockedSku(product_id=product_id, warehouse_id=warehouse_id, reason=reason))
    await db.commit()
    return await recommend_plan(db, trigger="sku_blocked")


async def unblock_sku(db: AsyncSession, product_id: int, warehouse_id: str) -> Plan | None:
    res = await db.execute(delete(BlockedSku).where(BlockedSku.product_id == product_id, BlockedSku.warehouse_id == warehouse_id))
    if res.rowcount == 0:
        raise NotFoundError("Not blocked")
    await db.commit()
    return await recommend_plan(db, trigger="sku_unblocked")


# ----------------------------------------------------------------- outlook (forecast x plan)
async def outlook(db: AsyncSession, plan: Plan, warehouse_id: str | None = None) -> list[dict]:
    """Stock after this plan vs the next N days of forecast demand, per SKU x warehouse."""
    view = await plan_view(db, plan, warehouse_id)
    planned: dict = {}
    for l in view["lines"]:
        q = l["qty_allocated"] if l["status"] == "COMMITTED" else l["final_qty"]
        if plan.status != PLAN_RECOMMENDED:
            q = l["final_qty"] or (l["qty_allocated"] if l["status"] == "COMMITTED" else 0.0)
        planned[(l["product_id"], l["warehouse_id"])] = planned.get((l["product_id"], l["warehouse_id"]), 0.0) + q
    pids = sorted({k[0] for k in planned})
    if not pids:
        return []
    days = settings.forecast_horizon_days
    totals = await asyncio.to_thread(forecast_service.demand_totals, days, pids)
    demand = {(r.product_id, r.warehouse_id): r.total_predicted_units for r in totals.itertuples()}
    stock = {(r.product_id, r.warehouse_id): r.stock_on_hand for r in (await _stock()).itertuples()}
    out = []
    for (pid, wh), qty in sorted(planned.items()):
        on_hand = float(stock.get((pid, wh), 0.0))
        left = on_hand - qty
        d = float(demand.get((pid, wh), 0.0))
        daily = d / days if days else 0
        cover = round(left / daily, 1) if daily > 0 else None
        if left <= 0:
            flag = "STOCKED_OUT"
        elif d > left:
            flag = "WILL_STOCK_OUT"
        elif cover is not None and cover < days * 1.5:
            flag = "LOW_COVER"
        else:
            flag = "OK"
        out.append({"product_id": pid, "warehouse_id": wh, "stock_on_hand": on_hand, "planned_dispatch": round(qty, 2),
                    "stock_after_plan": round(left, 2), "forecast_demand": round(d, 2), "forecast_days": days,
                    "days_of_cover": cover, "outlook": flag})
    return out
