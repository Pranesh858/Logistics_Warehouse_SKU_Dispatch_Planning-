"""What counts as worth telling somebody about.

Each rule is a sweep: it works out what is wrong *now* and hands back the full set, and `clear_missing`
closes whatever is no longer in it. That shape is deliberate. A rule that only ever raised alerts would
leave yesterday's stockout on the screen after the stock arrived, and a planner who has once seen a stale
alert stops believing the list.

The rules themselves:

  sync_failed        a feed from the WMS or ERP failed on its last run - our stock or order view is going stale
  stockout           nothing on the shelf and demand forecast for it
  low_cover          it will run out before a resupply could arrive, which is the one that costs money
  export_failed      approved orders did not reach the WMS, so their stock sits reserved and unshipped
  transfer_overdue   stock left one warehouse and never arrived
  retrain_rejected   a new model was worse, or the retrain failed, so the old model is still live
  retrain_done       a new model went live, at the lowest severity: the forecast changed under everyone
"""
import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.models import IntegrationRun
from app.modules.alerts import service as alerts
from app.modules.alerts.models import CRITICAL, INFO, WARNING
from app.modules.dispatch.models import (
    PLAN_PARTIAL, TRANSFER_IN_TRANSIT, ExportLog, LedgerEntry, Plan, StockTransfer,
)

STOCK_ALERT_LIMIT = 40          # the worst N, so one bad day cannot bury the list in 300 rows


# ----------------------------------------------------------------- feeds
async def check_feeds(db: AsyncSession) -> int:
    """A feed whose most recent run failed. While it is failing our picture of stock or orders is going stale,
    and every plan built on it is a little more wrong than the last."""
    # Ordered by id as well as time: stored timestamps have one-second granularity, so two runs of the same
    # feed in the same second would otherwise be in an arbitrary order and "the latest run" could be the
    # older one - which would leave an alert standing after the feed had recovered.
    runs = (await db.execute(select(IntegrationRun)
                             .order_by(IntegrationRun.started_at.desc(), IntegrationRun.id.desc())
                             .limit(200))).scalars().all()
    latest: dict[str, IntegrationRun] = {}
    for r in runs:
        latest.setdefault(r.feed, r)

    still_wrong = set()
    for feed, run in latest.items():
        key = f"sync_failed:{feed}"
        if run.status != "FAILED":
            continue
        still_wrong.add(key)
        await alerts.raise_alert(
            db, key=key, kind="sync_failed", severity=WARNING,
            title=f"The {feed} feed is failing",
            detail=(f"The last {feed} sync failed: {run.message or 'no reason given'}. "
                    f"Until it succeeds, the figures it supplies are as old as its last good run."),
        )
    return await alerts.clear_missing(db, "sync_failed", still_wrong)


# ----------------------------------------------------------------- stock
async def check_stock(db: AsyncSession) -> int:
    """Out of stock, or about to be with no delivery due in time.

    The urgency comes from the ordering calculation rather than a stock threshold of its own: 200 units is
    plenty of one SKU and a day and a half of another, and only the forecast and the lead time know which.
    """
    from app.modules.forecast import orders as ordering
    from app.modules.forecast import supply

    reserved = await _reserved(db)
    leads = await supply.lead_times(db)
    coming = await supply.on_order(db)
    try:
        data = await asyncio.to_thread(ordering.compute, 7, True, None, reserved, False, leads,
                                       settings.default_lead_time_days, coming)
    except Exception as exc:  # noqa: BLE001  the forecast may not be warm yet; that is not an alert
        print(f"[alerts] stock check skipped: {exc}", flush=True)
        return 0

    urgent = [r for r in data["rows"] if r["priority"] == ordering.LEVELS[0]][:STOCK_ALERT_LIMIT]
    still_wrong = set()
    for r in urgent:
        empty = r["available"] <= 0
        kind = "stockout" if empty else "low_cover"
        key = f"{kind}:{r['product_id']}:{r['warehouse_id']}"
        still_wrong.add(key)
        name = r.get("product_name") or f"SKU {r['product_id']}"
        if empty:
            title = f"{name} is out of stock at {r['warehouse_id']}"
            detail = (f"Nothing free to sell, and {r['forecast_units']:g} units are forecast over the next "
                      f"{r['cover_days']} days. {r['units_to_order']:g} units need ordering; the supplier "
                      f"takes {r['lead_time_days']} day(s).")
            severity = CRITICAL
        else:
            title = f"{name} runs out in {r['days_of_cover']} days at {r['warehouse_id']}"
            detail = (f"{r['available']:g} units free to sell, selling at about "
                      f"{round(r['period_units'] / 7, 1):g} a day, and the supplier takes "
                      f"{r['lead_time_days']} day(s). Order {r['units_to_order']:g} units to stay covered.")
            severity = WARNING
        await alerts.raise_alert(db, key=key, kind=kind, severity=severity, title=title, detail=detail,
                                 warehouse_id=r["warehouse_id"], product_id=r["product_id"])

    cleared = 0
    for kind in ("stockout", "low_cover"):
        cleared += await alerts.clear_missing(db, kind, still_wrong)
    return cleared


async def _reserved(db: AsyncSession) -> dict:
    rows = (await db.execute(select(LedgerEntry).where(LedgerEntry.fulfilment == "RESERVED"))).scalars().all()
    out: dict = {}
    for r in rows:
        key = (int(r.product_id), r.warehouse_id)
        out[key] = out.get(key, 0.0) + float(r.qty_committed)
    return out


# ----------------------------------------------------------------- dispatch
async def check_exports(db: AsyncSession) -> int:
    """Approved orders that never reached the WMS. Their stock is reserved and the goods are not moving:
    the worst of both, and invisible unless somebody opens that plan."""
    plan = (await db.execute(select(Plan).where(Plan.status == PLAN_PARTIAL)
                             .order_by(Plan.version.desc()))).scalars().first()
    still_wrong = set()
    if plan is not None:
        failed = (await db.execute(select(ExportLog).where(ExportLog.plan_id == plan.id,
                                                           ExportLog.export_status != "SUCCESS"))).scalars().all()
        if failed:
            key = f"export_failed:plan:{plan.id}"
            still_wrong.add(key)
            await alerts.raise_alert(
                db, key=key, kind="export_failed", severity=CRITICAL,
                title=f"{len(failed)} approved order(s) did not reach the WMS",
                detail=(f"Plan v{plan.version} was approved but {len(failed)} order(s) failed to export. "
                        f"Their stock stays reserved while the goods sit still. Retry the send from the plan."),
            )
    return await alerts.clear_missing(db, "export_failed", still_wrong)


async def check_transfers(db: AsyncSession) -> int:
    """Stock that left one warehouse and has not arrived. Those units are on nobody's shelf."""
    rows = (await db.execute(select(StockTransfer)
                             .where(StockTransfer.status == TRANSFER_IN_TRANSIT))).scalars().all()
    now = datetime.now()
    still_wrong = set()
    for t in rows:
        if t.eta is None or t.eta >= now:
            continue
        key = f"transfer_overdue:{t.id}"
        still_wrong.add(key)
        late = (now - t.eta).days
        await alerts.raise_alert(
            db, key=key, kind="transfer_overdue", severity=WARNING,
            title=f"Transfer {t.transfer_ref} is {late} day(s) late",
            detail=(f"{t.qty:g} units of SKU {t.product_id} left {t.from_warehouse_id} for "
                    f"{t.to_warehouse_id} and were due on {t.eta:%d %b}. Until they are marked as arrived "
                    f"they count as nobody's stock."),
            warehouse_id=t.to_warehouse_id, product_id=int(t.product_id),
        )
    return await alerts.clear_missing(db, "transfer_overdue", still_wrong)


# ----------------------------------------------------------------- retraining
async def check_retrain(db: AsyncSession) -> int:
    """How the last retrain ended.

    This is swept rather than pushed because the outcome that matters most - a model rejected for being
    worse - never reaches a success callback. Reading the retrain's own status catches every ending:
    promoted, rejected and failed.
    """
    from app.modules.forecast import dataset

    state = dataset.status()
    result = state.get("result") or {}
    comparison = result.get("comparison") or {}
    still_wrong = set()

    if state.get("state") == "rejected":
        # Keyed on the figures, so the same rejection is one alert however often it is swept, and a later
        # retrain with a different outcome raises its own.
        key = f"retrain_rejected:{comparison.get('wape_before')}:{comparison.get('wape_after')}"
        still_wrong.add(key)
        await alerts.raise_alert(
            db, key=key, kind="retrain_rejected", severity=WARNING,
            title="A retrain was rejected: the new model was worse",
            detail=(f"Tested on the last {comparison.get('holdout_days')} days, error went from "
                    f"{comparison.get('wape_before')} to {comparison.get('wape_after')} "
                    f"({comparison.get('change_pct')}%). The previous model is still live, so forecasts are "
                    f"unaffected. Check the new data for gaps or wrong units."),
        )
    elif state.get("state") == "failed":
        key = f"retrain_failed:{state.get('error', '')[:60]}"
        still_wrong.add(key)
        await alerts.raise_alert(
            db, key=key, kind="retrain_rejected", severity=WARNING,
            title="A retrain failed before it finished",
            detail=f"{state.get('error') or 'No reason given.'} The previous model is still live.",
        )
    cleared = await alerts.clear_missing(db, "retrain_rejected", still_wrong)

    if state.get("state") == "done" and result.get("promoted"):
        k = result.get("accuracy") or {}
        extra = f" Daily error now {k['day_mape_pct']}%." if "day_mape_pct" in k else ""
        if result.get("accuracy_error"):
            extra = " The accuracy page could not be re-scored, so its figures still describe the old model."
        await alerts.raise_alert(
            db, key=f"retrain_done:{result.get('backup')}", kind="retrain_done", severity=INFO,
            title="A new forecast model is live",
            detail=(f"Trained on {result.get('training_rows')} rows up to {result.get('history_to')}."
                    f"{extra} The previous model is in the backup folder if it needs rolling back."),
        )
    return cleared


# ----------------------------------------------------------------- the sweep
async def sweep(db: AsyncSession) -> dict:
    """Run every rule. One rule failing must not stop the others; a half-swept list is better than none."""
    if not settings.alerts_enabled:
        return {"enabled": False}
    done = {}
    for name, rule in (("feeds", check_feeds), ("stock", check_stock), ("exports", check_exports),
                       ("transfers", check_transfers), ("retrain", check_retrain)):
        try:
            done[name] = await rule(db)
        except Exception as exc:  # noqa: BLE001
            done[name] = f"failed: {exc}"
            print(f"[alerts] rule {name} failed: {exc}", flush=True)
    try:
        done["pruned"] = await alerts.prune(db)
    except Exception as exc:  # noqa: BLE001
        done["pruned"] = f"failed: {exc}"
    done["live"] = await alerts.count_live(db)
    return done
