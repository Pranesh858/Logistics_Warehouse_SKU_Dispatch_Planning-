"""Pulling data in from the WMS / ERP and pushing purchase orders out. Every attempt is written to integration_runs."""
import asyncio
import secrets
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import locks
from app.core.config import settings
from app.integrations import clients, config_store
from app.integrations.models import IntegrationRun, PurchaseOrder, StockLevel
from app.ml import train
from app.ml.features import read_history
from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch import waves
from app.modules.dispatch.engine import TIER_RANK
from app.modules.dispatch.models import PLAN_RECOMMENDED, LedgerEntry, Order, Plan
from app.modules.dispatch.schemas import OrderIn
from app.modules.forecast import dataset as dataset_service
from app.modules.forecast import orders as order_needs
from app.modules.forecast.runtime import runtime
from app.modules.stock import service as stock_service
from app.modules.stock.models import SHIPMENT
from app.shared.exceptions import BadRequestError, NotFoundError

FEEDS = ("inventory", "orders", "sales", "purchasing", "dispatch")


async def _log(db: AsyncSession, feed: str, mode: str, status: str, rows: int, message: str) -> IntegrationRun:
    run = IntegrationRun(feed=feed, mode=mode, status=status, rows=rows, message=message[:1000])
    db.add(run)
    await db.commit()
    return run


# ------------------------------------------------------------------------------ inventory
async def apply_stock(db: AsyncSession, items: list[dict], source: str, username: str | None = None,
                      reason: str | None = None) -> tuple[int, int, int]:
    """Store reported stock counts. Returns (applied, changed, skipped). Unknown SKU/warehouse pairs are skipped, not
    fatal. Each figure that moved is recorded as an ADJUSTMENT in the stock ledger."""
    known = {(int(r.product_id), r.warehouse_id) for r in (await dispatch_service._stock()).itertuples()}
    counts: dict[tuple[int, str], float] = {}
    skipped = 0
    for it in items:
        try:
            key = (int(it["product_id"]), str(it["warehouse_id"]).strip().upper())
            qty = float(it["stock_on_hand"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if key not in known or qty < 0:
            skipped += 1
            continue
        counts[key] = qty
    changed = await stock_service.count(db, counts, source=source, username=username, reason=reason)
    applied = len(counts)
    if changed:
        await dispatch_service.recommend_plan(db, trigger="stock_update")
    return applied, changed, skipped


async def sync_inventory(db: AsyncSession) -> IntegrationRun:
    mode = clients.mode("inventory")
    try:
        items = await clients.inventory_source().fetch()
        applied, changed, skipped = await apply_stock(db, items, "wms")
    except Exception as exc:
        return await _log(db, "inventory", mode, "FAILED", 0, str(exc))
    note = f"{applied} SKU-warehouse stock levels received, {changed} changed"
    return await _log(db, "inventory", mode, "OK", applied, note + (f", {skipped} skipped (unknown SKU or warehouse)" if skipped else ""))


# ------------------------------------------------------------------------------ orders
async def add_erp_orders(db: AsyncSession, raw: list[dict], rebuild: bool = True) -> tuple[int, int]:
    """Add new orders from the ERP. Already-known and unusable orders are skipped one by one. Returns (added, skipped).
    `rebuild=False` stores them without a new plan; they join it at the next order sync.

    One batch at a time: two copies of the same order arriving together must not both pass the "already known"
    check, or the second would fail on the database's unique key instead of being skipped."""
    async with locks.named("erp-orders"):
        return await _add_erp_orders(db, raw, rebuild)


async def _add_erp_orders(db: AsyncSession, raw: list[dict], rebuild: bool = True) -> tuple[int, int]:
    snap = await dispatch_service._stock()
    valid_pairs = set(zip(snap["product_id"], snap["warehouse_id"]))
    # Known means open OR already dispatched. A shipped or cancelled order is deleted from the open orders, but the
    # ERP keeps listing it, so checking only the open orders imported it again as a new one.
    known_ids = set((await db.execute(select(Order.order_id))).scalars().all())
    known_ids |= set((await db.execute(select(LedgerEntry.order_id))).scalars().all())
    fresh: list[OrderIn] = []
    skipped = 0
    seen = set()
    for r in raw:
        try:
            o = OrderIn(**r)
        except Exception:
            skipped += 1
            continue
        if o.order_id in known_ids or o.order_id in seen or (o.product_id, o.warehouse_id) not in valid_pairs or o.customer_tier not in TIER_RANK:
            skipped += 1
            continue
        seen.add(o.order_id)
        fresh.append(o)
    if fresh:
        await dispatch_service.ingest_orders(db, fresh, rebuild=rebuild)
    return len(fresh), skipped


async def sync_orders(db: AsyncSession) -> IntegrationRun:
    mode = clients.mode("orders")
    try:
        since = (await db.execute(select(func.max(Order.order_timestamp)))).scalar_one_or_none()
        raw = await clients.order_source().fetch(since)
        added, skipped = await add_erp_orders(db, raw)
    except Exception as exc:
        return await _log(db, "orders", mode, "FAILED", 0, str(exc))
    msg = f"{added} new orders added" + (f", {skipped} skipped (already known or invalid)" if skipped else "")
    return await _log(db, "orders", mode, "OK", added, msg + ("; the dispatch plan was rebuilt" if added else ""))


# ------------------------------------------------------------------------------ sales history
def _append_sales(rows: list[dict]) -> tuple[int, list[int], list[str]]:
    """Blocking: validate, merge into the dataset file and reload the history. The model is NOT retrained here."""
    old = read_history()
    clean, errors, warnings = train.validate_upload(pd.DataFrame(rows))
    if errors:
        raise BadRequestError("; ".join(errors))
    merged, _ = train.merge_history(old, clean)
    new_products = sorted(set(clean["product_id"]) - set(old["product_id"]))
    out = merged.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(settings.dataset_path, index=False)
    runtime.reset()                       # the next forecast rebuilds its features from the longer history
    return len(clean), [int(p) for p in new_products], warnings


async def sync_sales(db: AsyncSession) -> IntegrationRun:
    mode = clients.mode("sales")
    if mode == "simulator" and not settings.simulate_sales:
        return await _log(db, "sales", mode, "OK", 0, "No ERP connected, so there is no sales feed. Sales history is not invented; "
                          "add real sales with Update sales data on the Demand forecast page.")
    if dataset_service.status()["state"] == "running":
        return await _log(db, "sales", mode, "FAILED", 0, "A model retrain is running; sales were not added. Try again when it finishes.")
    try:
        old_last = await asyncio.to_thread(lambda: runtime.frame["date"].max())
        raw = await clients.sales_source().fetch((old_last + pd.Timedelta(days=1)).date())
        if not raw:
            return await _log(db, "sales", mode, "OK", 0, "No new sales")
        n, new_products, warnings = await asyncio.to_thread(_append_sales, raw)
        await stock_service.register_from_history(db)      # a SKU new to the history becomes a stocked SKU
        await dispatch_service.recommend_plan(db, trigger="sales_update")
    except Exception as exc:
        return await _log(db, "sales", mode, "FAILED", 0, getattr(exc, "detail", None) or str(exc))
    msg = f"{n} sales rows added to the history; the model was not retrained"
    if new_products:
        msg += f". New SKUs {new_products} cannot be forecast until the model is retrained"
    return await _log(db, "sales", mode, "OK", n, msg)


# ------------------------------------------------------------------------------ dispatch confirmations
CLOSED = {"shipped": "SHIPPED", "cancelled": "CANCELLED"}


async def pending_confirmations(db: AsyncSession, warehouse_id: str | None) -> list[dict]:
    """Approved orders the WMS has not yet confirmed. Their stock is still held back."""
    q = select(LedgerEntry).where(LedgerEntry.fulfilment == "RESERVED").order_by(LedgerEntry.committed_at)
    if warehouse_id:
        q = q.where(LedgerEntry.warehouse_id == warehouse_id)
    rows = (await db.execute(q.limit(500))).scalars().all()
    return [{"order_id": r.order_id, "product_id": r.product_id, "warehouse_id": r.warehouse_id,
             "qty": r.qty_committed, "wms_status": r.wms_status,
             "committed_at": r.committed_at.isoformat() if r.committed_at else None} for r in rows]


async def confirm_dispatch(db: AsyncSession, items: list[dict], source: str, warehouse_id: str | None = None) -> dict:
    """The WMS tells us what really happened to approved orders.

    shipped   - the goods have left. The order is finished, so it leaves the plan, the reservation is released and
                the stock figure drops by what went out. Releasing the reservation without lowering the stock would
                let the same units be promised to somebody else.
    cancelled - the goods never left. The reservation is released and the stock stays where it is; the order is
                dropped, because it will not ship.
    """
    shipped = cancelled = skipped = 0
    freed = 0.0
    taken: list[stock_service.Move] = []
    # A WMS may send the same confirmation twice, and both copies may arrive at once. Only one may close the order
    # and take its stock off the shelf: the lock stops two requests here interleaving, and the update below only
    # changes a row that is still RESERVED, so even a second process could not close it twice.
    async with locks.named("dispatch-confirm"):
        for it in items:
            oid = str(it.get("order_id") or "").strip()
            state = CLOSED.get(str(it.get("status") or "shipped").strip().lower())
            row = await db.get(LedgerEntry, oid) if oid else None
            if row is None or state is None or row.fulfilment != "RESERVED" or (warehouse_id and row.warehouse_id != warehouse_id):
                skipped += 1
                continue
            closed = await db.execute(update(LedgerEntry)
                                      .where(LedgerEntry.order_id == oid, LedgerEntry.fulfilment == "RESERVED")
                                      .values(fulfilment=state, closed_at=datetime.now()))
            if closed.rowcount != 1:
                skipped += 1
                continue
            freed += float(row.qty_committed)
            if state == "SHIPPED":
                shipped += 1
                taken.append(stock_service.Move(int(row.product_id), row.warehouse_id, -float(row.qty_committed),
                                                SHIPMENT, ref=oid))
            else:
                cancelled += 1
            order = await db.get(Order, oid)      # finished or cancelled: either way it is no longer an open order
            if order is not None:
                await db.delete(order)
        await db.commit()
        # Goods that have left the building are no longer on the shelf, so stock drops by what shipped. Where a WMS
        # feed is connected its next report overwrites this with the authoritative figure.
        await stock_service.apply(db, taken, source=source)
    if shipped or cancelled:
        await dispatch_service.recommend_plan(db, trigger="dispatch_confirmed")
    msg = f"{shipped} shipped, {cancelled} cancelled, {round(freed):g} units released from reservation"
    if skipped:
        msg += f", {skipped} skipped (unknown order or already confirmed)"
    await _log(db, "dispatch", source, "OK", shipped + cancelled, msg)
    return {"shipped": shipped, "cancelled": cancelled, "skipped": skipped, "units_released": round(freed, 2), "message": msg}


# ------------------------------------------------------------------------------ purchase orders
def _po_payload(po: PurchaseOrder) -> dict:
    return {"po_ref": po.po_ref, "warehouse_id": po.warehouse_id, "lines": po.lines, "total_units": po.total_units}


async def _send_po(db: AsyncSession, po: PurchaseOrder) -> PurchaseOrder:
    try:
        ok, ref, err = await clients.purchase_sink().create(_po_payload(po))
    except Exception as exc:
        ok, ref, err = False, None, str(exc)
    po.status, po.erp_reference, po.error = ("SENT", ref, None) if ok else ("FAILED", None, err)
    await db.commit()
    await db.refresh(po)
    await _log(db, "purchasing", clients.mode("purchasing"), "OK" if ok else "FAILED", po.total_units if ok else 0,
               f"{po.po_ref} for {po.warehouse_id}: " + (f"sent to ERP ({ref})" if ok else f"not sent: {err}"))
    return po


async def create_purchase_orders(db: AsyncSession, days: int, safety: bool, warehouse_id: str | None, urgent_only: bool,
                                 user: str) -> list[PurchaseOrder]:
    """One purchase order per warehouse, built here from the same numbers as the Units to order list."""
    from app.modules.forecast.router import _reserved
    res = await asyncio.to_thread(order_needs.compute, days, safety, warehouse_id, await _reserved(db))
    rows = [r for r in res["rows"] if r["units_to_order"] > 0 and (not urgent_only or r["priority"] != "Plan ahead")]
    if not rows:
        raise BadRequestError("Nothing to order for this selection")
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    pos = []
    for wh in sorted({r["warehouse_id"] for r in rows}):
        lines = [{"product_id": r["product_id"], "product_name": r["product_name"], "units": r["units_to_order"], "priority": r["priority"]}
                 for r in rows if r["warehouse_id"] == wh]
        po = PurchaseOrder(po_ref=f"PO-{wh}-{stamp}-{secrets.token_hex(2).upper()}", warehouse_id=wh, status="FAILED", total_units=sum(l["units"] for l in lines), lines=lines,
                           period_days=days, safety_buffer=int(safety), created_by=user)
        db.add(po)
        await db.commit()
        pos.append(await _send_po(db, po))
    return pos


async def retry_purchase_order(db: AsyncSession, po_id: int) -> PurchaseOrder:
    po = await db.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError("Purchase order not found")
    if po.status == "SENT":
        raise BadRequestError("This purchase order was already sent")
    po.attempts += 1
    return await _send_po(db, po)


# ------------------------------------------------------------------------------ scheduled retraining
async def _last_retrain(db: AsyncSession):
    return (await db.execute(select(IntegrationRun).where(IntegrationRun.feed == "retrain", IntegrationRun.status == "OK")
                             .order_by(IntegrationRun.id.desc()).limit(1))).scalar_one_or_none()


async def maybe_retrain(db: AsyncSession, session_factory) -> IntegrationRun | None:
    """Retrain on the grown sales history every RETRAIN_EVERY_DAYS days. The new model replaces the current one
    only if it is not clearly less accurate on the most recent weeks."""
    days = settings.retrain_every_days
    if days <= 0 or dataset_service.status()["state"] == "running":
        return None
    last = await _last_retrain(db)
    if last is not None and (datetime.now() - last.started_at).days < days:
        return None
    loop = asyncio.get_running_loop()

    def done(result):
        async def after():
            async with session_factory() as s2:
                c = result.get("comparison", {})
                await _log(s2, "retrain", "scheduled", "OK", result.get("training_rows", 0),
                           f"Retrained on history to {result.get('history_to')}: error {c.get('wape_before')} -> {c.get('wape_after')}")
                await stock_service.register_from_history(s2)
                await dispatch_service.recommend_plan(s2, trigger="retrained")
        asyncio.run_coroutine_threadsafe(after(), loop)

    await asyncio.to_thread(dataset_service.start_retrain, done, "scheduled")
    return await _log(db, "retrain", "scheduled", "OK", 0, "Scheduled retrain started")


# ------------------------------------------------------------------------------ status
PULLED = ("inventory", "orders", "sales")


async def status(db: AsyncSession) -> dict:
    feeds = []
    labels = {"inventory": ("Stock levels", "WMS"), "orders": ("Customer orders", "ERP"), "sales": ("Sales history", "ERP"),
              "purchasing": ("Purchase orders", "ERP"), "dispatch": ("Dispatch orders", "WMS")}
    for feed in FEEDS:
        last = (await db.execute(select(IntegrationRun).where(IntegrationRun.feed == feed).order_by(IntegrationRun.id.desc()).limit(1))).scalar_one_or_none()
        ok = (await db.execute(select(IntegrationRun).where(IntegrationRun.feed == feed, IntegrationRun.status == "OK")
                               .order_by(IntegrationRun.id.desc()).limit(1))).scalar_one_or_none()
        mode = clients.mode(feed)
        feeds.append({
            "feed": feed, "label": labels[feed][0], "system": labels[feed][1], "mode": mode,
            "auto_minutes": config_store.sync_minutes(feed) if feed in PULLED else None,
            "last": None if last is None else {"status": last.status, "rows": last.rows, "message": last.message, "at": last.started_at.isoformat()},
            "last_ok_at": None if ok is None else ok.started_at.isoformat(),
        })
    dispatch_mode = clients.mode("dispatch")
    return {
        "feeds": feeds, "dispatch_export": {"system": "WMS", "mode": dispatch_mode},
        "live_stock_skus": (await db.execute(select(func.count()).select_from(StockLevel).where(
            StockLevel.source.in_(("wms", "webhook"))))).scalar_one(), "webhooks_enabled": bool(settings.integration_webhook_key),
        "systems": {s: _system_view(s) for s in config_store.SYSTEMS},
        "awaiting_confirmation": (await db.execute(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.fulfilment == "RESERVED"))).scalar_one(),
    }


def _system_view(system: str) -> dict:
    """What the admin may see. The key itself is never sent back, only whether one is set."""
    c = config_store.get(system)
    return {"system": system, "base_url": c["base_url"], "enabled": c["enabled"], "has_key": bool(c["api_key"]),
            "field_map": c.get("field_map") or {}, "sync_minutes": c.get("sync_minutes") or {},
            "source": c.get("source", "env"), "updated_by": c.get("updated_by"), "updated_at": c.get("updated_at"),
            "feeds": list(config_store.FEEDS_OF[system])}


async def recent_runs(db: AsyncSession, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(IntegrationRun).order_by(IntegrationRun.id.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "feed": r.feed, "mode": r.mode, "status": r.status, "rows": r.rows, "message": r.message, "at": r.started_at.isoformat()} for r in rows]


def po_out(po: PurchaseOrder) -> dict:
    return {"id": po.id, "po_ref": po.po_ref, "warehouse_id": po.warehouse_id, "status": po.status, "erp_reference": po.erp_reference,
            "total_units": po.total_units, "lines": po.lines, "period_days": po.period_days, "safety_buffer": bool(po.safety_buffer),
            "created_by": po.created_by, "error": po.error, "attempts": po.attempts,
            "received_at": po.received_at.isoformat() if po.received_at else None, "received_by": po.received_by,
            "created_at": po.created_at.isoformat() if po.created_at else None}


# ------------------------------------------------------------------------------ scheduler
async def wave_tick(session_factory, since: datetime, now: datetime) -> None:
    """What the dispatch waves need between two scheduler ticks.

    * An order cut-off passed: pull the orders once more (when the order feed syncs on a schedule), so an order
      placed just before the cut-off makes its wave even if the regular sync falls later.
    * The plan is for a wave whose trucks have left (or was built before waves): build the next wave's plan. Orders
      that were not sent are carried into it.
    """
    wave = waves.current(now)
    if wave is None:
        return
    if config_store.sync_minutes("orders") > 0 and waves.cutoffs_between(since, now):
        async with session_factory() as db:
            await sync_orders(db)
    async with session_factory() as db:
        plan = (await db.execute(select(Plan).where(Plan.status == PLAN_RECOMMENDED)
                                 .order_by(Plan.version.desc()))).scalars().first()
        if plan is not None and plan.wave != wave.key:
            await dispatch_service.recommend_plan(db, trigger="next_wave")


async def scheduler(session_factory) -> None:
    """Runs each enabled feed on its own interval, and the dispatch waves. A failure is logged and the loop carries on."""
    tick = 30
    last: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    runners = {"inventory": sync_inventory, "orders": sync_orders, "sales": sync_sales}
    wave_since = waves.clock()
    while True:
        now = loop.time()
        try:
            wave_now = waves.clock()
            await wave_tick(session_factory, wave_since, wave_now)
            wave_since = wave_now
        except Exception as exc:  # noqa: BLE001
            print(f"[waves] {exc}", flush=True)
        for feed in PULLED:
            minutes = config_store.sync_minutes(feed)
            if minutes > 0 and now - last.get(feed, now - minutes * 60 - 1) >= minutes * 60:
                last[feed] = now
                try:
                    async with session_factory() as db:
                        await runners[feed](db)
                except Exception:
                    pass
        try:
            async with session_factory() as db:
                await maybe_retrain(db, session_factory)
        except Exception:
            pass
        await asyncio.sleep(tick)
