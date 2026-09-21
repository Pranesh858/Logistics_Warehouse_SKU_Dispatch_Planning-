"""
Batch recursive forecasting: runs recursive_predict.py's logic across ALL SKUs
(or a specified subset) and outputs one combined forecast table/CSV.

Usage:
    python batch_forecast.py --days 7
    python batch_forecast.py --days 30 --skus 1,2,3,4,5
    python batch_forecast.py --days 7 --out my_forecast.csv
    python batch_forecast.py --days 30 --rollup          # also saves a monthly-total summary
"""
import os
import argparse
import pandas as pd
from tqdm import tqdm
from features import build_feature_frame
from recursive_predict import load_models, recursive_forecast
from monthly_rollup import aggregate_forecast

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))


def batch_forecast(df, models, sku_ids, horizon_days=7):
    all_forecasts = []
    failed = []
    for sku_id in tqdm(sku_ids, desc="Forecasting SKUs"):
        try:
            f = recursive_forecast(df, models, sku_id, horizon_days)
            f.insert(0, "product_id", sku_id)
            all_forecasts.append(f)
        except Exception as e:
            failed.append((sku_id, str(e)))
    result = pd.concat(all_forecasts, ignore_index=True) if all_forecasts else pd.DataFrame()
    return result, failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7, help="Forecast horizon in days")
    parser.add_argument("--skus", type=str, default=None,
                         help="Comma-separated SKU IDs (default: all SKUs in the dataset)")
    parser.add_argument("--out", type=str, default="forecast_all_skus.csv",
                         help="Output CSV filename")
    parser.add_argument("--rollup", action="store_true",
                         help="Also compute and save a period-total (e.g., monthly) summary per SKU")
    parser.add_argument("--rollup-out", type=str, default="forecast_totals.csv",
                         help="Output filename for the rollup summary (used with --rollup)")
    args = parser.parse_args()

    print("Loading model and data...")
    models, meta = load_models()
    df = build_feature_frame()

    if args.skus:
        sku_ids = [int(s.strip()) for s in args.skus.split(",")]
    else:
        sku_ids = sorted(df["product_id"].unique().tolist())

    print(f"\nModel: {meta['model_version']}  (validated MAPE: {meta['validated_mape_pct']}%)")
    print(f"Forecasting {len(sku_ids)} SKUs, {args.days}-day horizon...\n")

    result, failed = batch_forecast(df, models, sku_ids, args.days)

    out_path = os.path.join(MODEL_DIR, args.out)
    result.to_csv(out_path, index=False)

    print(f"\nDone. {len(sku_ids) - len(failed)} SKUs forecasted successfully.")
    if failed:
        print(f"{len(failed)} SKUs failed:")
        for sku_id, err in failed[:10]:
            print(f"  SKU {sku_id}: {err}")

    print(f"\nSaved: {out_path}  ({len(result)} rows)")
    print("\nPreview (first 10 rows):")
    print(result.head(10).to_string(index=False))

    if args.rollup and not result.empty:
        rollup = aggregate_forecast(result)
        numeric_cols = ["total_p10", "total_p50", "total_p90"]
        rollup[numeric_cols] = rollup[numeric_cols].round(1)
        rollup_path = os.path.join(MODEL_DIR, args.rollup_out)
        rollup.to_csv(rollup_path, index=False)
        print(f"\n--- Period Totals (Rollup) ---")
        print(f"Saved: {rollup_path}  ({len(rollup)} SKUs)")
        print(rollup.head(10).to_string(index=False))
