"""
Inference script for the final deployed quick-commerce model
(qc_final_model.pkl). Same recursive multi-step forecasting approach as
m5_predict.py, adapted to this dataset's schema.

v4 change: a planner asking for an N-day forecast needs BOTH views --
the day-by-day breakdown (to see spikes/dips, plan daily dispatch) AND
the total units summed across the whole window (to size a single bulk
dispatch/purchase order). Previously only the day-wise CSV was produced;
this version always computes and saves both, so the planner picks
whichever view fits the decision instead of re-running anything.

Usage:
    python3 qc_predict_v4.py --days 7
    python3 qc_predict_v4.py --days 7 --products 10 --warehouses WH03
"""
import argparse
import json
import joblib
import numpy as np
import pandas as pd

from qc_features import build_feature_frame, add_lag_and_rolling_features

MODEL_PATH = "qc_final_model.pkl"
METADATA_PATH = "qc_model_metadata.json"


def load_model(model_path=MODEL_PATH, metadata_path=METADATA_PATH):
    model = joblib.load(model_path)
    with open(metadata_path) as f:
        meta = json.load(f)
    return model, meta


class InputValidationError(ValueError):
    """Raised when a forecast request references data the model was never
    trained on, or contains physically impossible values. Stress-testing
    showed the model will NOT raise an error on its own for these cases --
    it silently returns a number, which is the dangerous failure mode. This
    layer exists specifically to turn that into a loud, visible error."""
    pass


def validate_request(df, product_ids, warehouse_ids, known_products, known_warehouses):
    if product_ids is not None:
        unknown = set(product_ids) - known_products
        if unknown:
            raise InputValidationError(
                f"Unknown product_id(s) {sorted(unknown)} -- not present in training data. "
                f"A new SKU must be added to the dataset and the model retrained before it can be forecast."
            )
    if warehouse_ids is not None:
        unknown = set(warehouse_ids) - known_warehouses
        if unknown:
            raise InputValidationError(
                f"Unknown warehouse_id(s) {sorted(unknown)} -- not present in training data. "
                f"A new warehouse must be added to the dataset and the model retrained before it can be forecast."
            )


def validate_feature_values(df):
    """Catch physically impossible values BEFORE they silently reach the
    model (negative price, discount outside 0-100%, negative stock)."""
    errors = []
    if (df["price"] < 0).any():
        errors.append(f"{(df['price'] < 0).sum()} row(s) have negative price")
    if ((df["discount_pct"] < 0) | (df["discount_pct"] > 100)).any():
        n = ((df["discount_pct"] < 0) | (df["discount_pct"] > 100)).sum()
        errors.append(f"{n} row(s) have discount_pct outside 0-100%")
    if (df["stock_on_hand"] < 0).any():
        errors.append(f"{(df['stock_on_hand'] < 0).sum()} row(s) have negative stock_on_hand")
    if errors:
        raise InputValidationError("Invalid input data: " + "; ".join(errors))


def forecast_next_days(model, meta, days=7, path=None, product_ids=None, warehouse_ids=None,
                       frame=None, feature_log=None):
    """
    product_ids: None (all SKUs), a single int/str, or a list -- forecasts
        the whole catalog, one SKU, or a selected subset, respectively.
    warehouse_ids: same idea, to narrow by warehouse.
    Filtering happens BEFORE the recursive loop, so each product+warehouse's
    own lag/rolling history is computed correctly regardless of how many
    other SKUs are included.
    """
    # frame: an already-built feature frame (used by backtests, which must
    # truncate history at a past cut-off date). feature_log: pass an empty
    # list to receive the exact model input rows used at each forecast
    # step -- this is what the explainability module reads.
    if frame is not None:
        df = frame.copy()
    else:
        df = build_feature_frame(path) if path else build_feature_frame()
    feature_cols = meta["feature_cols"]

    known_products = set(df["product_id"].unique())
    known_warehouses = set(df["warehouse_id"].unique())
    validate_request(
        df,
        list(product_ids) if product_ids is not None and isinstance(product_ids, (list, tuple, set)) else ([product_ids] if product_ids is not None else None),
        list(warehouse_ids) if warehouse_ids is not None and isinstance(warehouse_ids, (list, tuple, set)) else ([warehouse_ids] if warehouse_ids is not None else None),
        known_products, known_warehouses,
    )
    validate_feature_values(df)

    if product_ids is not None:
        if not isinstance(product_ids, (list, tuple, set)):
            product_ids = [product_ids]
        df = df[df["product_id"].isin(product_ids)].copy()
        if df.empty:
            raise ValueError(f"No rows found for product_ids={product_ids}")

    if warehouse_ids is not None:
        if not isinstance(warehouse_ids, (list, tuple, set)):
            warehouse_ids = [warehouse_ids]
        df = df[df["warehouse_id"].isin(warehouse_ids)].copy()
        if df.empty:
            raise ValueError(f"No rows found for warehouse_ids={warehouse_ids}")

    last_date = df["date"].max()
    history = df.copy()
    all_forecasts = []

    for step in range(1, days + 1):
        target_date = last_date + pd.Timedelta(days=step)

        latest = (
            history.sort_values("date")
            .groupby(["product_id", "warehouse_id"], as_index=False)
            .tail(1)
            .copy()
        )

        latest["date"] = target_date
        latest["day_of_week"] = target_date.dayofweek
        latest["is_weekend"] = int(target_date.dayofweek >= 5)
        latest["month"] = target_date.month
        latest["day_of_month"] = target_date.day
        latest["week_of_year"] = int(target_date.isocalendar()[1])
        # no future calendar/promo plan known beyond history -- a real
        # deployment would plug in the actual upcoming promo calendar here
        latest["is_holiday"] = 0
        latest["promotion_flag"] = 0
        latest["discount_pct"] = 0

        X = latest[feature_cols]
        if feature_log is not None:
            logged = X.copy()
            logged.insert(0, "date", target_date)
            logged.insert(0, "warehouse_id", latest["warehouse_id"].values)
            logged.insert(0, "product_id", latest["product_id"].values)
            logged.insert(0, "step", step)
            feature_log.append(logged)
        preds = np.clip(model.predict(X), 0, None)
        latest["units_sold"] = preds
        latest["predicted_units"] = preds

        all_forecasts.append(
            latest[["product_id", "warehouse_id", "city", "date", "predicted_units"]].copy()
        )

        history = pd.concat([history, latest], ignore_index=True, sort=False)
        history = history.sort_values(["product_id", "warehouse_id", "date"])
        history = add_lag_and_rolling_features(history.drop(
            columns=[c for c in history.columns if c.startswith("lag_") or c.startswith("roll_")]
        ))

    result = pd.concat(all_forecasts, ignore_index=True)
    result["predicted_units"] = result["predicted_units"].round(2)
    return result.sort_values(["product_id", "warehouse_id", "date"]).reset_index(drop=True)


def summarize_totals(daywise_df, days):
    """
    Collapses the day-wise forecast into total predicted units over the
    whole window, at three levels a planner might want:
      1. Per SKU x warehouse (most granular -- e.g. "how much of SKU 10
         do I need to dispatch to WH03 over the next 7 days")
      2. Per SKU, across all its warehouses combined
      3. Grand total, across every SKU and warehouse in the request

    Returns (sku_warehouse_totals, sku_totals, grand_total) -- the first
    two as DataFrames, the last as a single float.
    """
    sku_warehouse_totals = (
        daywise_df.groupby(["product_id", "warehouse_id", "city"], as_index=False)["predicted_units"]
        .sum()
        .rename(columns={"predicted_units": "total_predicted_units"})
    )
    sku_warehouse_totals["total_predicted_units"] = sku_warehouse_totals["total_predicted_units"].round(2)
    sku_warehouse_totals["forecast_days"] = days
    sku_warehouse_totals = sku_warehouse_totals.sort_values(
        ["product_id", "warehouse_id"]
    ).reset_index(drop=True)

    sku_totals = (
        daywise_df.groupby(["product_id"], as_index=False)["predicted_units"]
        .sum()
        .rename(columns={"predicted_units": "total_predicted_units"})
    )
    sku_totals["total_predicted_units"] = sku_totals["total_predicted_units"].round(2)
    sku_totals["forecast_days"] = days
    sku_totals = sku_totals.sort_values("product_id").reset_index(drop=True)

    grand_total = round(float(daywise_df["predicted_units"].sum()), 2)

    return sku_warehouse_totals, sku_totals, grand_total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", type=str, default="qc_forecast_daywise.csv",
                         help="Output file for the day-by-day forecast.")
    parser.add_argument("--totals-out", type=str, default="qc_forecast_totals.csv",
                         help="Output file for the SKU x warehouse total-units summary.")
    parser.add_argument("--products", type=str, default=None,
                         help="Comma-separated product_id list, e.g. --products 1 or --products 1,5,10. Omit for all SKUs.")
    parser.add_argument("--warehouses", type=str, default=None,
                         help="Comma-separated warehouse_id list, e.g. --warehouses WH01,WH02. Omit for all warehouses.")
    parser.add_argument("--dataset", type=str, default=None,
                         help="Path to an alternate input CSV (same schema as quick_commerce_with_events_clean.csv). "
                              "Omit to use the default bundled / WMS-synced dataset.")
    parser.add_argument("--json-out", type=str, default=None,
                         help="If set, also writes a single JSON file with daywise rows, totals, and grand_total "
                              "-- lets a caller (e.g. the frontend API route) skip CSV parsing.")
    args = parser.parse_args()

    product_ids = [int(p) for p in args.products.split(",")] if args.products else None
    warehouse_ids = args.warehouses.split(",") if args.warehouses else None

    print("Loading final model...")
    model, meta = load_model()
    print(f"Model: LightGBM, objective={meta['objective']}, "
          f"trained on {meta['training_rows']:,} rows "
          f"({meta['products']} products x {meta['warehouses']} warehouses, {meta['cities']} cities)")
    print(f"Validated CV metrics: WAPE={meta['cv_metrics']['avg_wape']}, "
          f"MAPE={meta['cv_metrics']['avg_mape_pct']}%")
    print(f"BRD KPI status: {meta['brd_kpi_status']}")

    scope = f"product_ids={product_ids}" if product_ids else "ALL SKUs"
    scope += f", warehouse_ids={warehouse_ids}" if warehouse_ids else ", ALL warehouses"
    print(f"\nForecasting next {args.days} days for {scope}...")
    daywise_df = forecast_next_days(
        model, meta, days=args.days, path=args.dataset,
        product_ids=product_ids, warehouse_ids=warehouse_ids,
    )

    sku_warehouse_totals, sku_totals, grand_total = summarize_totals(daywise_df, args.days)

    # Confidence ranges (80%) from the rolling-origin backtest -- see
    # qc_backtest.py / qc_explain.py. Silently skipped if the intervals
    # file has not been generated yet.
    try:
        from qc_explain import add_ranges, total_range, load_intervals
        _iv = load_intervals()
        if _iv is not None:
            daywise_df = add_ranges(daywise_df, _iv)
            rng = [total_range(t, args.days, _iv) for t in sku_warehouse_totals["total_predicted_units"]]
            sku_warehouse_totals["total_low"] = [r[0] for r in rng]
            sku_warehouse_totals["total_high"] = [r[1] for r in rng]
    except ImportError:
        pass

    daywise_df.to_csv(args.out, index=False)
    sku_warehouse_totals.to_csv(args.totals_out, index=False)

    print(f"\nSaved {len(daywise_df):,} day-wise rows to {args.out}")
    print("Day-wise preview:")
    print(daywise_df.head(10).to_string())

    print(f"\nSaved {len(sku_warehouse_totals):,} SKU x warehouse totals to {args.totals_out}")
    print(f"(total predicted units summed across all {args.days} forecast days)")
    print("Totals preview:")
    print(sku_warehouse_totals.head(10).to_string())

    print(f"\nGRAND TOTAL across this request's full scope, over {args.days} days: {grand_total:,.2f} units")

    if args.json_out:
        payload = {
            "days": args.days,
            "scope": scope,
            "daywise": daywise_df.to_dict(orient="records"),
            "totals": sku_warehouse_totals.to_dict(orient="records"),
            "grand_total": grand_total,
            "model_meta": {
                "avg_wape": meta["cv_metrics"]["avg_wape"],
                "avg_mape_pct": meta["cv_metrics"]["avg_mape_pct"],
                "brd_kpi_status": meta["brd_kpi_status"],
            },
        }
        # daywise "date" column is a Timestamp -- stringify before JSON dump
        for row in payload["daywise"]:
            row["date"] = str(row["date"])[:10]
        with open(args.json_out, "w") as f:
            json.dump(payload, f)
        print(f"\nAlso wrote combined JSON to {args.json_out}")
