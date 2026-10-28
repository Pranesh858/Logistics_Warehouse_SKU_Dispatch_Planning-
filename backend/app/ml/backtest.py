"""Measuring the forecast against what really happened.

The accuracy page reads one file, `backtest.json`. Until now that file was produced once, offline, by a
script that never reached the repository: after a retrain the page went on showing the old model's figures,
which is the worst kind of wrong, because it looks right. This module rebuilds the file from the model and
the history that are live now.

The test is deliberately honest about what a forecast is:

  * The model is retrained up to each cut-off date, so it has never seen the days it is scored on.
  * The forecast runs recursively, the same way the application forecasts the future: day two is predicted
    from day one's *prediction*, not from what was really sold. Feeding true lags back in would flatter the
    model and would not be the thing the planner relies on.
  * Four cut-offs 14 days apart, each scored over the next 14 days, so the windows do not overlap and one
    unusual fortnight cannot carry the whole figure.

Field by field, `backtest.json` holds:

  kpis.day_*          error over every SKU x warehouse x day row
  kpis.sku_week_*     error on 7-day totals per SKU, which is the number ordering actually depends on
  daily               predicted vs actual per day, summed over SKUs
  daily_by_warehouse  the same, per warehouse
  by_horizon          error by how far ahead the day was, 1 to 14
  by_warehouse        error per warehouse over the whole window
  by_sku              per SKU: the 7-day totals averaged over the cut-offs, and the error at each
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import settings
from app.ml import predict, train
from app.ml.features import load_data

HORIZON_DAYS = 14
ORIGIN_COUNT = 4
WEEK = 7
NOTE = ("Backtest on past data: the model was retrained up to each cut-off date and its forecast compared "
        "with actual sales.")
KEYS = ["product_id", "warehouse_id"]


def _mape_pct(actual, predicted) -> float:
    """Mean absolute percentage error, in percent. Rows with no sales are skipped: a percentage of zero is
    not a number anyone can act on, and including them as 100% would swamp everything else."""
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    keep = actual > 0
    if not keep.any():
        return 0.0
    return float(np.mean(np.abs(actual[keep] - predicted[keep]) / actual[keep]) * 100)


def _bias_pct(actual, predicted) -> float:
    """Over- or under-forecast across the whole set. Negative means the forecast came in low."""
    total = float(np.asarray(actual, float).sum())
    if not total:
        return 0.0
    return float((np.asarray(predicted, float).sum() - total) / total * 100)


def origins(frame: pd.DataFrame, horizon: int = HORIZON_DAYS, count: int = ORIGIN_COUNT) -> list[pd.Timestamp]:
    """Cut-off dates, oldest first, so the last window ends on the final day of the history."""
    last = pd.Timestamp(frame["date"].max())
    first = pd.Timestamp(frame["date"].min())
    out = [last - pd.Timedelta(days=horizon * (i + 1)) for i in range(count)]
    # A cut-off needs enough history behind it to train on at all; lag_28 alone reaches back a month.
    return sorted(d for d in out if d - first >= pd.Timedelta(days=train.MIN_DAYS_PER_SKU))


def _one_origin(frame: pd.DataFrame, raw: pd.DataFrame, origin: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """Train up to `origin`, forecast the next `horizon` days, and line the forecast up against the truth."""
    past = frame[frame["date"] <= origin]
    model = train.fit(past)
    meta = {"feature_cols": train.FEATURE_COLS}
    forecast = predict.forecast_next_days(model, meta, days=horizon, frame=past)

    window = raw[(raw["date"] > origin) & (raw["date"] <= origin + pd.Timedelta(days=horizon))]
    actual = window[KEYS + ["date", "units_sold"]].rename(columns={"units_sold": "actual"})
    out = forecast.merge(actual, on=KEYS + ["date"], how="inner")
    out = out.rename(columns={"predicted_units": "predicted"})
    out["origin"] = origin
    out["horizon_day"] = (out["date"] - origin).dt.days
    return out


def run(raw: pd.DataFrame | None = None, horizon: int = HORIZON_DAYS, count: int = ORIGIN_COUNT,
        progress=None) -> dict:
    """Score the forecast and return the report. Does not write anything; `save` does that.

    progress: optional callable(done, total, message) so a long retrain can say where it has got to.
    """
    raw = load_data() if raw is None else raw.copy()
    raw["date"] = pd.to_datetime(raw["date"])
    frame = train.features_from_raw(raw)
    cutoffs = origins(frame, horizon, count)
    if not cutoffs:
        raise ValueError("Not enough history to score a forecast against: need more days than the lags reach back.")

    parts = []
    for i, origin in enumerate(cutoffs, start=1):
        if progress:
            progress(i - 1, len(cutoffs), f"Scoring the forecast from {origin.date()}")
        parts.append(_one_origin(frame, raw, origin, horizon))
    rows = pd.concat(parts, ignore_index=True)
    if rows.empty:
        raise ValueError("The forecast and the sales history did not overlap on any day.")
    if progress:
        progress(len(cutoffs), len(cutoffs), "Summarising")
    return _report(rows, cutoffs, horizon)


def _report(rows: pd.DataFrame, cutoffs: list[pd.Timestamp], horizon: int) -> dict:
    by_sku = _by_sku(rows)
    sku_errs = [r["mean_abs_err_pct"] for r in by_sku if r["mean_abs_err_pct"] is not None]
    weeks = _sku_weeks(rows)                     # one row per SKU per cut-off, not averaged
    daily = rows.groupby("date", as_index=False)[["predicted", "actual"]].sum().sort_values("date")

    return {
        "note": NOTE,
        "horizon_days": horizon,
        "origins": [str(d.date()) for d in cutoffs],
        "period": {"start": str(rows["date"].min().date()), "end": str(rows["date"].max().date())},
        "target_mape_pct": float(settings.accuracy_target_mape_pct),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpis": {
            "day_wape": round(train.wape(rows["actual"], rows["predicted"]), 3),
            "day_mape_pct": round(_mape_pct(rows["actual"], rows["predicted"]), 1),
            "day_bias_pct": round(_bias_pct(rows["actual"], rows["predicted"]), 1),
            # Each SKU's week is scored on its own: averaging the cut-offs first would let a week over and a
            # week under cancel, and report an accuracy nobody experienced.
            "sku_week_wape": round(train.wape(weeks["actual"], weeks["predicted"]), 3),
            "sku_week_mape_pct": round(sum(sku_errs) / len(sku_errs), 1) if sku_errs else 0.0,
            "total_predicted": round(float(rows["predicted"].sum()), 1),
            "total_actual": round(float(rows["actual"].sum()), 1),
            "sku_day_rows": int(len(rows)),
            "skus": int(rows["product_id"].nunique()),
        },
        "daily": [{"date": str(r.date.date()), "predicted": round(float(r.predicted), 1),
                   "actual": round(float(r.actual), 1)} for r in daily.itertuples()],
        "daily_by_warehouse": _daily_by_warehouse(rows),
        "by_horizon": _by_horizon(rows),
        "by_warehouse": _by_warehouse(rows),
        "by_sku": by_sku,
    }


def _daily_by_warehouse(rows: pd.DataFrame) -> dict:
    out: dict[str, list] = {}
    grouped = rows.groupby(["warehouse_id", "date"], as_index=False)[["predicted", "actual"]].sum()
    for wh, part in grouped.groupby("warehouse_id"):
        out[str(wh)] = [{"date": str(r.date.date()), "predicted": round(float(r.predicted), 1),
                         "actual": round(float(r.actual), 1)}
                        for r in part.sort_values("date").itertuples()]
    return out


def _by_horizon(rows: pd.DataFrame) -> list[dict]:
    out = []
    for day, part in rows.groupby("horizon_day"):
        out.append({"horizon_day": int(day),
                    "wape": round(train.wape(part["actual"], part["predicted"]), 3),
                    "mape_pct": round(_mape_pct(part["actual"], part["predicted"]), 1)})
    return sorted(out, key=lambda r: r["horizon_day"])


def _by_warehouse(rows: pd.DataFrame) -> list[dict]:
    out = []
    for wh, part in rows.groupby("warehouse_id"):
        out.append({"warehouse_id": str(wh),
                    "wape": round(train.wape(part["actual"], part["predicted"]), 3),
                    "mape_pct": round(_mape_pct(part["actual"], part["predicted"]), 1),
                    "bias_pct": round(_bias_pct(part["actual"], part["predicted"]), 1),
                    "predicted": round(float(part["predicted"].sum()), 1),
                    "actual": round(float(part["actual"].sum()), 1)})
    return sorted(out, key=lambda r: r["warehouse_id"])


def _sku_weeks(rows: pd.DataFrame) -> pd.DataFrame:
    """7-day totals per SKU x warehouse x cut-off: the unit an order quantity is actually sized against."""
    week = rows[rows["horizon_day"] <= WEEK]
    return week.groupby(KEYS + ["origin"], as_index=False)[["predicted", "actual"]].sum()


def _by_sku(rows: pd.DataFrame) -> list[dict]:
    """Per SKU: the first week of each cut-off, averaged over the cut-offs.

    Averaging the totals and averaging the errors are two different things, and both are here on purpose.
    forecast_7d vs actual_7d is the typical week, which is what an order quantity is sized against;
    mean_abs_err_pct is how far out a single week was, which does not shrink when overs and unders cancel.
    """
    out = []
    for (pid, wh), part in _sku_weeks(rows).groupby(KEYS):
        weeks = [(float(r.predicted), float(r.actual)) for r in part.itertuples() if r.actual > 0]
        errs = [abs(f - a) / a * 100 for f, a in weeks]
        bias = [(f - a) / a * 100 for f, a in weeks]
        out.append({
            "product_id": int(pid),
            "warehouse_id": str(wh),
            "forecast_7d": round(float(part["predicted"].mean()), 1),
            "actual_7d": round(float(part["actual"].mean()), 1),
            "mean_abs_err_pct": round(sum(errs) / len(errs), 1) if errs else None,
            "bias_pct": round(sum(bias) / len(bias), 1) if bias else 0.0,
        })
    return sorted(out, key=lambda r: (r["product_id"], r["warehouse_id"]))


def save(report: dict, path: str | Path | None = None) -> Path:
    """Write the report where the accuracy page reads it. Written to a temporary file and moved into place,
    so a page loading at the wrong moment never sees half a file."""
    dest = Path(path or settings.backtest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(dest)
    return dest


def refresh(raw: pd.DataFrame | None = None, progress=None) -> dict:
    """Score the live model's data and replace the accuracy report. Returns the new KPIs."""
    report = run(raw, progress=progress)
    save(report)
    return report["kpis"]
