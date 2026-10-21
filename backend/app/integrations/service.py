"""Pulling data in from the WMS / ERP and pushing purchase orders out. Every attempt is written to integration_runs."""
import asyncio
import secrets
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations import clients
from app.integrations.models import IntegrationRun, PurchaseOrder, StockLevel
from app.ml import train
from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch.engine import TIER_RANK
from app.modules.dispatch.models import Order
from app.modules.dispatch.schemas import OrderIn
from app.modules.forecast import dataset as dataset_service
from app.modules.forecast import orders as order_needs
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError, NotFoundError

FEEDS = ("inventory", "orders", "sales", "purchasing")


async def _log(db: AsyncSession, feed: str, mode: str, status: str, rows: int, message: str) -> IntegrationRun:
    run = IntegrationRun(feed=feed, mode=mode, status=status, rows=rows, message=message[:1000])
    db.add(run)
    await db.commit()
    return run


async def load_overlay(db: AsyncSession) -> int:
    """At startup: put the last known WMS stock back in front of the sales-history stock."""
    rows = (await db.execute(select(StockLevel))).scalars().all()
    runtime.set_live_stock({(r.product_id, r.warehouse_id): r.qty for r in rows})
    return len(rows)


# ------------------------------------------------------------------------------ inventory
async def apply_stock(db: AsyncSession, items: list[dict], source: str) -> tuple[int, int, int]:
    """Store reported stock. Returns (applied, changed, skipped). Unknown SKU/warehouse pairs are skipped, not fatal."""
    known = {(int(r.product_id), r.warehouse_id): float(r.stock_on_hand) for r in (await dispatch_service._stock()).itertuples()}
    existing = {(r.product_id, r.warehouse_id): r for r in (await db.execute(select(StockLevel))).scalars().all()}
    applied = changed = skipped = 0
    live = dict(runtime._live_stock)
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
        applied += 1
        if abs(known[key] - qty) > 1e-6:
            changed += 1
        row = existing.get(key)
        if row is None:
            db.add(StockLevel(product_id=key[0], warehouse_id=key[1], qty=qty, source=source, updated_at=datetime.now()))
        else:
            row.qty, row.source, row.updated_at = qty, source, datetime.now()
        live[key] = qty
    await db.commit()
    runtime.set_live_stock(live)
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
async def add_erp_orders(db: AsyncSession, raw: list[dict]) -> tuple[int, int]:
    """Add new orders from the ERP. Already-known and unusable orders are skipped one by one. Returns (added, skipped)."""
    snap = await dispatch_service._stock()
    valid_pairs = set(zip(snap["product_id"], snap["warehouse_id"]))
    known_ids = set((await db.execute(select(Order.order_id))).scalars().all())
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
        await dispatch_service.ingest_orders(db, fresh)
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
    old = pd.read_csv(settings.dataset_path, parse_dates=["date"])
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
        await dispatch_service.recommend_plan(db, trigger="sales_update")
    except Exception as exc:
        return await _log(db, "sales", mode, "FAILED", 0, getattr(exc, "detail", None) or str(exc))
    msg = f"{n} sales rows added to the history; the model was not retrained"
    if new_products:
        msg += f". New SKUs {new_products} cannot be forecast until the model is retrained"
    return await _log(db, "sales", mode, "OK", n, msg)


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


# ------------------------------------------------------------------------------ status
INTERVALS = {"inventory": "inventory_sync_minutes", "orders": "order_sync_minutes", "sales": "sales_sync_minutes"}


async def status(db: AsyncSession) -> dict:
    feeds = []
    labels = {"inventory": ("Stock levels", "WMS"), "orders": ("Customer orders", "ERP"), "sales": ("Sales history", "ERP"),
              "purchasing": ("Purchase orders", "ERP")}
    for feed in FEEDS:
        last = (await db.execute(select(IntegrationRun).where(IntegrationRun.feed == feed).order_by(IntegrationRun.id.desc()).limit(1))).scalar_one_or_none()
        ok = (await db.execute(select(IntegrationRun).where(IntegrationRun.feed == feed, IntegrationRun.status == "OK")
                               .order_by(IntegrationRun.id.desc()).limit(1))).scalar_one_or_none()
        mode = clients.mode(feed)
        feeds.append({
            "feed": feed, "label": labels[feed][0], "system": labels[feed][1], "mode": mode,
            "auto_minutes": getattr(settings, INTERVALS[feed], 0) if feed in INTERVALS else None,
            "last": None if last is None else {"status": last.status, "rows": last.rows, "message": last.message, "at": last.started_at.isoformat()},
            "last_ok_at": None if ok is None else ok.started_at.isoformat(),
        })
    dispatch_mode = "live" if settings.wms_base_url else "simulator"
    return {
        "feeds": feeds, "dispatch_export": {"system": "WMS", "mode": dispatch_mode},
        "live_stock_skus": runtime.live_stock_count(), "webhooks_enabled": bool(settings.integration_webhook_key),
    }


async def recent_runs(db: AsyncSession, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(IntegrationRun).order_by(IntegrationRun.id.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "feed": r.feed, "mode": r.mode, "status": r.status, "rows": r.rows, "message": r.message, "at": r.started_at.isoformat()} for r in rows]


def po_out(po: PurchaseOrder) -> dict:
    return {"id": po.id, "po_ref": po.po_ref, "warehouse_id": po.warehouse_id, "status": po.status, "erp_reference": po.erp_reference,
            "total_units": po.total_units, "lines": po.lines, "period_days": po.period_days, "safety_buffer": bool(po.safety_buffer),
            "created_by": po.created_by, "error": po.error, "attempts": po.attempts, "created_at": po.created_at.isoformat() if po.created_at else None}


# ------------------------------------------------------------------------------ scheduler
async def scheduler(session_factory) -> None:
    """Runs each enabled feed on its own interval. A failure is logged and the loop carries on."""
    tick = 30
    last: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    runners = {"inventory": sync_inventory, "orders": sync_orders, "sales": sync_sales}
    while True:
        now = loop.time()
        for feed, attr in INTERVALS.items():
            minutes = getattr(settings, attr)
            if minutes > 0 and now - last.get(feed, now - minutes * 60 - 1) >= minutes * 60:
                last[feed] = now
                try:
                    async with session_factory() as db:
                        await runners[feed](db)
                except Exception:
                    pass
        await asyncio.sleep(tick)
