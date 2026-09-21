"""
Prediction interface: load the trained model and forecast demand for any SKU
over a configurable horizon, with confidence intervals.

Usage:
    python predict.py --sku 4 --days 7
"""
import argparse
import pandas as pd
import numpy as np
import joblib
import json
from features import build_feature_frame
from train_model import FEATURE_COLS

import os
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))

def load_models():
    models = {
        0.1: joblib.load(f"{MODEL_DIR}/model_p10.pkl"),
        0.5: joblib.load(f"{MODEL_DIR}/model_p50.pkl"),
        0.9: joblib.load(f"{MODEL_DIR}/model_p90.pkl"),
    }
    with open(f"{MODEL_DIR}/model_metadata.json") as f:
        meta = json.load(f)
    return models, meta

def forecast_sku(df, models, sku_id, horizon_days=7):
    """Forecast the next `horizon_days` for a given SKU using its most recent
    feature row as the base (in production this would step forward day-by-day,
    updating lag features with each new prediction; here we use the last known
    feature snapshot as a representative near-term forecast)."""
    sku_rows = df[df["product_id"] == sku_id].sort_values("date")
    if sku_rows.empty:
        raise ValueError(f"No data for SKU {sku_id}")

    last_row = sku_rows.iloc[[-1]]
    last_date = last_row["date"].values[0]

    results = []
    for d in range(1, horizon_days + 1):
        X = last_row[FEATURE_COLS]
        p10 = max(0, models[0.1].predict(X)[0])
        p50 = max(0, models[0.5].predict(X)[0])
        p90 = max(0, models[0.9].predict(X)[0])
        p10, p90 = min(p10, p50), max(p90, p50)
        results.append({
            "date": pd.Timestamp(last_date) + pd.Timedelta(days=d),
            "forecast_p10": round(p10, 1),
            "forecast_p50": round(p50, 1),
            "forecast_p90": round(p90, 1),
        })
    return pd.DataFrame(results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", type=int, default=4)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    print("Loading model and data...")
    models, meta = load_models()
    df = build_feature_frame()

    print(f"\nModel: {meta['model_version']}  (trained {meta['trained_at'][:10]})")
    print(f"Validated accuracy: MAPE {meta['validated_mape_pct']}% (target: {meta['kpi_target']})")

    sku_name = df[df["product_id"] == args.sku]["product_name"].iloc[0]
    print(f"\nForecast for SKU {args.sku} ({sku_name}), next {args.days} days:")

    forecast = forecast_sku(df, models, args.sku, args.days)
    print(forecast.to_string(index=False))
