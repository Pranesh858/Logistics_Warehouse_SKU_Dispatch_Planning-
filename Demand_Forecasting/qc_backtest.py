"""
Forecast accuracy against actuals (BRD FC-FR-003) -- an honest, leak-free
backtest of the way the forecast is actually USED.

Why this differs from the cross-validation in qc_train_model.py:
the CV folds score one-day-ahead predictions using the TRUE previous days'
sales as lag features. A planner asking for a 7-day forecast gets a
RECURSIVE forecast, where day 5 is built on predicted days 1-4. Accuracy
at longer horizons is therefore lower than the CV figure, and the planner
should see by how much. This script measures that directly:

  for each cut-off date T (several, going back in time):
      1. retrain the model using ONLY data up to T
      2. forecast T+1 ... T+H recursively, exactly as production does
      3. compare against what really sold on those days

Outputs
  qc_backtest_by_horizon.csv   WAPE / MAPE for forecast day 1, 2, ... H
  qc_backtest_by_sku.csv       per SKU x warehouse: 7-day forecast vs actual
  qc_forecast_intervals.json   empirical low/high multipliers per horizon day,
                               used to give every forecast a confidence range

Notes
  * Future promotions/holidays are unknown at forecast time, so (as in
    production) the forecast assumes none; actual days with a promo or
    holiday are scored anyway -- that is a real limitation, not hidden.
  * Days when the shelf was empty (stockout) are scored as recorded.

Usage:
    python3 qc_backtest.py
    python3 qc_backtest.py --horizon 14 --origins 3
"""
import argparse
import json
import numpy as np
import pandas as pd
import lightgbm as lgb

from qc_features import build_feature_frame
from qc_train_model import prepare_dataset, FEATURE_COLS, CAT_COLS, TARGET, wape, mape
from qc_predict_final import forecast_next_days, load_model

PARAMS = dict(
    objective="tweedie", tweedie_variance_power=1.1,
    n_estimators=300, learning_rate=0.05,
    num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1,
)
KEYS = ["product_id", "warehouse_id"]


def run_origin(full, cutoff, horizon, meta):
    hist = full[full["date"] <= cutoff]
    trainable = prepare_dataset(hist)
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(trainable[FEATURE_COLS], trainable[TARGET], categorical_feature=CAT_COLS)

    fc = forecast_next_days(model, meta, days=horizon, frame=hist)
    fc["horizon_day"] = (fc["date"] - cutoff).dt.days
    actual = full[(full["date"] > cutoff) & (full["date"] <= cutoff + pd.Timedelta(days=horizon))]
    actual = actual[KEYS + ["date", "units_sold"]]
    m = fc.merge(actual, on=KEYS + ["date"], how="inner")
    m["origin"] = cutoff
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=14)
    ap.add_argument("--origins", type=int, default=3)
    ap.add_argument("--spacing", type=int, default=14, help="days between cut-off dates")
    args = ap.parse_args()

    _, meta = load_model()
    full = build_feature_frame()
    last = full["date"].max()

    frames = []
    for k in range(args.origins):
        cutoff = last - pd.Timedelta(days=args.horizon + k * args.spacing)
        print(f"Origin {k + 1}/{args.origins}: train through {cutoff.date()}, "
              f"forecast {args.horizon} days ahead, score vs actuals ...")
        frames.append(run_origin(full, cutoff, args.horizon, meta))
    allm = pd.concat(frames, ignore_index=True)
    allm = allm.rename(columns={"predicted_units": "pred", "units_sold": "actual"})

    # ---- accuracy by forecast day -------------------------------------
    rows = []
    for h, g in allm.groupby("horizon_day"):
        rows.append({"horizon_day": int(h), "n": len(g),
                     "wape": round(wape(g["actual"].values, g["pred"].values), 3),
                     "mape_pct": round(mape(g["actual"].values, g["pred"].values), 1)})
    by_h = pd.DataFrame(rows)
    by_h.to_csv("qc_backtest_by_horizon.csv", index=False)

    # ---- SKU-week level (the BRD KPI's stated granularity) -------------
    wk = allm[allm["horizon_day"] <= 7].groupby(KEYS + ["origin"], as_index=False)[["pred", "actual"]].sum()
    wk["abs_err_pct"] = np.where(wk["actual"] > 0, (wk["pred"] - wk["actual"]).abs() / wk["actual"] * 100, np.nan)
    wk["bias_pct"] = np.where(wk["actual"] > 0, (wk["pred"] - wk["actual"]) / wk["actual"] * 100, np.nan)
    sku_week_wape = (wk["pred"] - wk["actual"]).abs().sum() / wk["actual"].sum()
    sku_week_mape = wk["abs_err_pct"].mean()

    by_sku = wk.groupby(KEYS, as_index=False).agg(
        forecast_7d=("pred", "mean"), actual_7d=("actual", "mean"),
        mean_abs_err_pct=("abs_err_pct", "mean"), bias_pct=("bias_pct", "mean"))
    by_sku[["forecast_7d", "actual_7d", "mean_abs_err_pct", "bias_pct"]] = \
        by_sku[["forecast_7d", "actual_7d", "mean_abs_err_pct", "bias_pct"]].round(1)
    by_sku.to_csv("qc_backtest_by_sku.csv", index=False)

    # ---- empirical confidence ranges per horizon day --------------------
    # ratio = actual / predicted on days with a positive prediction;
    # low/high = 10th / 90th percentile -> an 80% interval.
    intervals = {}
    pos = allm[allm["pred"] > 0].copy()
    pos["ratio"] = pos["actual"] / pos["pred"]
    for h, g in pos.groupby("horizon_day"):
        intervals[str(int(h))] = {"low": round(float(g["ratio"].quantile(0.10)), 3),
                                   "high": round(float(g["ratio"].quantile(0.90)), 3)}
    # week totals are less noisy than single days -> own interval for sums
    wk_pos = wk[wk["pred"] > 0]
    wr = wk_pos["actual"] / wk_pos["pred"]
    # cumulative totals: sum of forecast days 1..h per SKU x origin, for each h
    cum = {}
    for h in range(1, args.horizon + 1):
        g = allm[allm["horizon_day"] <= h].groupby(KEYS + ["origin"], as_index=False)[["pred", "actual"]].sum()
        g = g[g["pred"] > 0]
        r = g["actual"] / g["pred"]
        cum[str(h)] = {"low": round(float(r.quantile(0.10)), 3), "high": round(float(r.quantile(0.90)), 3)}
    summary = {
        "method": "empirical 10th/90th percentile of actual/predicted, from rolling-origin backtest",
        "coverage": "80% interval",
        "origins": args.origins, "horizon": args.horizon,
        "daily": intervals,
        "cumulative_total": cum,
        "sku_week_total": {"low": round(float(wr.quantile(0.10)), 3), "high": round(float(wr.quantile(0.90)), 3)},
        "sku_week_wape": round(float(sku_week_wape), 3),
        "sku_week_mape_pct": round(float(sku_week_mape), 1),
    }
    with open("qc_forecast_intervals.json", "w") as f:
        json.dump(summary, f, indent=2)

    pd.set_option("display.width", 160)
    print("\n=== Accuracy by forecast day (recursive, leak-free) ===")
    print(by_h.to_string(index=False))
    print(f"\nSKU x warehouse, 7-day totals ({len(wk)} scored forecasts): "
          f"WAPE={sku_week_wape:.3f}  MAPE={sku_week_mape:.1f}%")
    print(f"80% interval on a 7-day SKU total: x{summary['sku_week_total']['low']} to x{summary['sku_week_total']['high']} of forecast")
