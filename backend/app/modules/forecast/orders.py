"""Units to order.

The question is not "how much will this SKU sell this week" but "how much do I need so the shelf does not run
empty before the next delivery lands". So the cover period is the supplier's lead time plus the period until
the next order, and anything already on its way is counted before ordering more.
"""
import math
import threading

import pandas as pd

from app.core.config import settings
from app.ml.explain import load_intervals, total_range
from app.ml.predict import InputValidationError, forecast_next_days
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError

PERIODS = (7, 14, 28)
LEVELS = ["Order now", "Order soon", "Plan ahead"]
KEYS = ["product_id", "warehouse_id"]


def _level(available: float, cover: float | None, lead: int) -> str:
    """Urgency is measured against the delivery wait: running out before stock can arrive is the emergency."""
    if available <= 0 or (cover is not None and cover < max(3, lead)):
        return LEVELS[0]
    if cover is not None and cover < max(7, lead * 2):
        return LEVELS[1]
    return LEVELS[2]


_cache: dict = {}
_cache_lock = threading.Lock()
MAX_DAYS = max(PERIODS) + 30            # the longest period plus the longest lead time we allow


def _daywise(days: int, warehouse_id: str | None) -> pd.DataFrame:
    """The forecast is recursive, so the first 7 days of a 28-day run are the 7-day run. Run 28 days once per
    scope and reuse it until the model or the history changes."""
    key = (warehouse_id, id(runtime.model), id(runtime.frame))
    with _cache_lock:
        full = _cache.get(key)
        if full is None:
            _cache.clear()
            full = forecast_next_days(runtime.model, runtime.meta, days=MAX_DAYS,
                                      warehouse_ids=[warehouse_id] if warehouse_id else None, frame=runtime.frame)
            _cache[key] = full
    last = full["date"].min() + pd.Timedelta(days=days - 1)
    return full[full["date"] <= last]


def warm() -> None:
    """Compute the network-wide forecast ahead of time (after a retrain)."""
    _daywise(MAX_DAYS, None)


def compute(days: int, safety: bool, warehouse_id: str | None, reserved: dict, include_all: bool = False,
            lead_times: dict[int, int] | None = None, default_lead: int | None = None,
            on_order: dict | None = None) -> dict:
    """Rows are SKU x warehouse.

        cover days   = supplier lead time + the chosen period
        units needed = forecast over those days (upper end of the 80% range when `safety`)
                       - stock free to sell (on hand, less what approved orders already hold)
                       - units already on order and not yet received
                       never below zero
    """
    if days not in PERIODS:
        raise BadRequestError("Choose 7, 14 or 28 days")
    lead_times = lead_times or {}
    on_order = on_order or {}
    default_lead = settings.default_lead_time_days if default_lead is None else default_lead
    horizon = min(days + max([default_lead, *lead_times.values()], default=default_lead), MAX_DAYS)
    try:
        daywise = _daywise(horizon, warehouse_id)
    except InputValidationError as exc:
        raise BadRequestError(str(exc)) from exc

    # Each SKU is summed over its own cover window, because lead times differ.
    daywise = daywise.sort_values(KEYS + ["date"])
    daywise["day"] = daywise.groupby(KEYS).cumcount() + 1
    iv = load_intervals()

    snap = runtime.stock_snapshot()
    meta = snap[KEYS + ["city", "stock_on_hand"]].merge(runtime.sku_info(), on="product_id", how="left")
    lookup = {(int(r.product_id), r.warehouse_id): r for r in meta.itertuples()}

    rows = []
    for (pid, wh), group in daywise.groupby(KEYS, sort=False):
        pid = int(pid)
        lead = int(lead_times.get(pid, default_lead))
        window = min(days + lead, MAX_DAYS)
        expected = float(group[group["day"] <= window]["predicted_units"].sum())
        period_only = float(group[group["day"] <= days]["predicted_units"].sum())
        low, high = total_range(expected, window, iv)
        high = float(high if high is not None else expected)

        info_row = lookup.get((pid, wh))
        on_hand = float(getattr(info_row, "stock_on_hand", 0) or 0)
        held = float(reserved.get((pid, wh), 0.0))
        coming = float(on_order.get((pid, wh), 0.0))
        available = max(on_hand - held, 0.0)
        planning = high if safety else expected
        need = max(0, math.ceil(planning - available - coming))

        daily = period_only / days if days else 0
        cover = round(available / daily, 1) if daily > 0 else None
        rows.append({
            "product_id": pid, "product_name": getattr(info_row, "product_name", None),
            "category": getattr(info_row, "category", None), "warehouse_id": wh,
            "city": getattr(info_row, "city", None),
            "forecast_units": round(expected, 1), "forecast_high": round(high, 1),
            "period_units": round(period_only, 1), "lead_time_days": lead, "cover_days": window,
            "stock_on_hand": round(on_hand, 1), "reserved": round(held, 1), "on_order": round(coming, 1),
            "available": round(available, 1), "days_of_cover": cover,
            "units_to_order": need, "priority": _level(available, cover, lead) if need else "Covered",
        })
    order = {k: i for i, k in enumerate(LEVELS + ["Covered"])}
    rows.sort(key=lambda x: (order[x["priority"]], x["days_of_cover"] if x["days_of_cover"] is not None else 1e9,
                             -x["units_to_order"]))
    todo = [x for x in rows if x["units_to_order"] > 0]
    by_wh = {}
    for x in todo:
        d = by_wh.setdefault(x["warehouse_id"], {"warehouse_id": x["warehouse_id"], "city": x["city"], "skus": 0, "units": 0})
        d["skus"] += 1
        d["units"] += x["units_to_order"]
    in_period = daywise[daywise["day"] <= days]
    daily = in_period.groupby("date", as_index=False)["predicted_units"].sum()
    grand = round(float(in_period["predicted_units"].sum()), 1)
    return {
        "days": days, "safety_buffer": safety, "warehouse_id": warehouse_id,
        "default_lead_time_days": default_lead,
        "on_order_units": int(sum(x["on_order"] for x in rows)),
        "history_to": runtime.meta["training_date_range"][1],
        "summary": {
            "skus_to_order": len(todo), "units_to_order": int(sum(x["units_to_order"] for x in todo)),
            "order_now": sum(1 for x in todo if x["priority"] == LEVELS[0]),
            "order_soon": sum(1 for x in todo if x["priority"] == LEVELS[1]),
            "forecast_units": round(grand, 1), "skus_checked": len(rows),
        },
        "by_warehouse": sorted(by_wh.values(), key=lambda d: -d["units"]),
        "daily": [{"date": d.strftime("%Y-%m-%d"), "units": round(float(u), 1)} for d, u in zip(daily["date"], daily["predicted_units"])],
        "rows": rows if include_all else todo,
    }
