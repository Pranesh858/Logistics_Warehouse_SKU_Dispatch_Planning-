"""Confidence ranges and plain-English drivers for a forecast (ported from qc_explain.py)."""
import json
import os
import numpy as np
import pandas as pd

from app.core.config import settings
from app.ml.features import build_feature_frame
from app.ml.predict import forecast_next_days

DRIVER_GROUPS = {
    "Recent sales level and trend": ["lag_1", "lag_7", "lag_14", "lag_28",
                                      "roll_mean_7", "roll_std_7", "roll_mean_14",
                                      "roll_std_14", "roll_mean_28", "roll_std_28"],
    "Day of week and season": ["day_of_week", "is_weekend", "month", "day_of_month", "week_of_year"],
    "Holiday and events": ["is_holiday", "event_type_1_cat"],
    "Price and promotion": ["price", "discount_pct", "promotion_flag"],
    "Product and location profile": ["category_cat", "warehouse_id_cat", "product_id_cat",
                                      "city_cat", "is_organic_flag", "shelf_life_days", "weight_g"],
}


def load_intervals(path=None):
    path = path or settings.intervals_path
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _factor(intervals, section, key):
    """Look up multipliers for horizon day `key`; beyond the backtested
    horizon, reuse the furthest one measured rather than invent a number."""
    table = intervals[section]
    k = str(key)
    if k not in table:
        k = str(max(int(x) for x in table))
    return table[k]["low"], table[k]["high"]


def add_ranges(daywise_df, intervals=None):
    """Adds predicted_low / predicted_high to a day-wise forecast. Used by
    qc_predict_final.py so every forecast carries its uncertainty."""
    intervals = intervals or load_intervals()
    if intervals is None:
        return daywise_df
    df = daywise_df.sort_values(["product_id", "warehouse_id", "date"]).copy()
    df["_h"] = df.groupby(["product_id", "warehouse_id"]).cumcount() + 1
    lows, highs = [], []
    for h in df["_h"]:
        lo, hi = _factor(intervals, "daily", h)
        lows.append(lo)
        highs.append(hi)
    df["predicted_low"] = (df["predicted_units"] * np.array(lows)).round(2)
    df["predicted_high"] = (df["predicted_units"] * np.array(highs)).round(2)
    return df.drop(columns="_h").reset_index(drop=True)


def total_range(total_units, days, intervals=None):
    """80% range for a TOTAL over `days` days. Errors on different days
    partly cancel, so this is much tighter than summing daily ranges --
    it comes from the backtest of cumulative totals, not from addition."""
    intervals = intervals or load_intervals()
    if intervals is None:
        return None, None
    lo, hi = _factor(intervals, "cumulative_total", days)
    return round(total_units * lo, 2), round(total_units * hi, 2)


def _reason(group, factor):
    """Plain-English line. Effects are measured against the AVERAGE SKU's
    baseline, so a high-volume item shows a large multiplier on its recent
    sales -- that is correct, and reads better as 'x4.1' than '+311%'."""
    pct = (factor - 1) * 100
    if abs(pct) < 3:
        return f"{group}: roughly neutral"
    if factor >= 1.5:
        return f"{group}: x{factor:.1f} vs the average SKU (pushes the forecast up)"
    if factor <= 0.67:
        return f"{group}: x{factor:.2f} vs the average SKU (pulls the forecast down)"
    direction = "raises" if pct > 0 else "lowers"
    return f"{group} {direction} the forecast by about {abs(pct):.0f}%"


def explain(model, meta, product_id, warehouse_id, days=7, history_days=14, full=None):
    if full is None:
        full = build_feature_frame()
    feature_log = []
    daywise = forecast_next_days(model, meta, days=days, product_ids=[product_id],
                                 warehouse_ids=[warehouse_id], frame=full, feature_log=feature_log)
    X = pd.concat(feature_log, ignore_index=True)
    cols = meta["feature_cols"]

    contrib = model.predict(X[cols], pred_contrib=True)  # (n, n_features + 1), log space
    contrib = np.asarray(contrib)
    baseline_log = contrib[:, -1]

    # internal consistency: exp(sum of contributions) must equal the prediction
    recon = np.exp(contrib.sum(axis=1))
    served = np.clip(model.predict(X[cols]), 0, None)
    assert np.allclose(recon, served, rtol=1e-4, atol=1e-4), "driver factors do not reproduce the prediction"

    intervals = load_intervals()
    daywise = add_ranges(daywise, intervals)

    out_days = []
    for i, row in daywise.reset_index(drop=True).iterrows():
        drivers = []
        for group, feats in DRIVER_GROUPS.items():
            idx = [cols.index(f) for f in feats if f in cols]
            factor = float(np.exp(contrib[i, idx].sum()))
            drivers.append({"driver": group, "factor": round(factor, 3),
                            "effect_pct": round((factor - 1) * 100, 1),
                            "reason": _reason(group, factor)})
        drivers.sort(key=lambda d: abs(np.log(d["factor"])), reverse=True)
        out_days.append({
            "date": str(row["date"])[:10],
            "predicted_units": float(row["predicted_units"]),
            "range_80pct": [float(row.get("predicted_low", np.nan)), float(row.get("predicted_high", np.nan))],
            "baseline_units": round(float(np.exp(baseline_log[i])), 2),
            "drivers": drivers,
        })

    hist = full[(full["product_id"] == product_id) & (full["warehouse_id"] == warehouse_id)] \
        .sort_values("date").tail(history_days)
    history = [{"date": str(d)[:10], "units_sold": float(u)} for d, u in zip(hist["date"], hist["units_sold"])]

    total = float(daywise["predicted_units"].sum())
    lo, hi = total_range(total, days, intervals)
    return {
        "product_id": product_id, "warehouse_id": warehouse_id,
        "city": str(daywise["city"].iloc[0]), "days": days,
        "total_predicted_units": round(total, 2),
        "total_range_80pct": [lo, hi],
        "recent_actuals": history,
        "forecast": out_days,
        "how_to_read": "factor > 1 raises the forecast above the baseline; < 1 lowers it. "
                       "Factors multiply with the baseline to give the prediction.",
    }
