"""Units to order: what the forecast says will sell over a period, less what is already on the shelf."""
import math
import threading

import pandas as pd

from app.ml.explain import add_ranges, load_intervals, total_range
from app.ml.predict import InputValidationError, forecast_next_days, summarize_totals
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError

PERIODS = (7, 14, 28)
LEVELS = ["Order now", "Order soon", "Plan ahead"]


def _level(available: float, cover: float | None, days: int) -> str:
    if available <= 0 or (cover is not None and cover < 3):
        return LEVELS[0]
    if cover is not None and cover < 7:
        return LEVELS[1]
    return LEVELS[2]


_cache: dict = {}
_cache_lock = threading.Lock()
MAX_DAYS = max(PERIODS)


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


def compute(days: int, safety: bool, warehouse_id: str | None, reserved: dict, include_all: bool = False) -> dict:
    """Rows are SKU x warehouse. needed = forecast over `days` (upper end of the 80% range when `safety`)
    - (stock on hand - stock already promised to approved orders), never below zero."""
    if days not in PERIODS:
        raise BadRequestError("Choose 7, 14 or 28 days")
    try:
        daywise = _daywise(days, warehouse_id)
    except InputValidationError as exc:
        raise BadRequestError(str(exc)) from exc
    totals, _, grand = summarize_totals(daywise, days)
    iv = load_intervals()
    ranges = [total_range(t, days, iv) for t in totals["total_predicted_units"]]
    totals["low"] = [r[0] if r[0] is not None else t for r, t in zip(ranges, totals["total_predicted_units"])]
    totals["high"] = [r[1] if r[1] is not None else t for r, t in zip(ranges, totals["total_predicted_units"])]

    snap = runtime.stock_snapshot()
    info = runtime.frame.drop_duplicates(KEYS := ["product_id", "warehouse_id"])[KEYS + ["product_name", "category"]]
    df = totals.merge(snap[KEYS + ["stock_on_hand"]], on=KEYS, how="left").merge(info, on=KEYS, how="left")

    rows = []
    for r in df.itertuples():
        on_hand = float(r.stock_on_hand or 0)
        held = float(reserved.get((r.product_id, r.warehouse_id), 0.0))
        available = max(on_hand - held, 0.0)
        expected = float(r.total_predicted_units)
        planning = float(r.high) if safety else expected
        need = max(0, math.ceil(planning - available))
        daily = expected / days if days else 0
        cover = round(available / daily, 1) if daily > 0 else None
        rows.append({
            "product_id": int(r.product_id), "product_name": r.product_name, "category": r.category,
            "warehouse_id": r.warehouse_id, "city": r.city, "forecast_units": round(expected, 1),
            "forecast_high": round(float(r.high), 1), "stock_on_hand": round(on_hand, 1),
            "reserved": round(held, 1), "available": round(available, 1), "days_of_cover": cover,
            "units_to_order": need, "priority": _level(available, cover, days) if need else "Covered",
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
    daily = (daywise.groupby("date", as_index=False)["predicted_units"].sum())
    return {
        "days": days, "safety_buffer": safety, "warehouse_id": warehouse_id,
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
