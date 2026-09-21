"""
Recursive multi-step forecasting.

Each future day's prediction is fed back in as the new "yesterday" before
predicting the next day, so lag/rolling features update step by step instead
of reusing the same static snapshot for every day in the horizon.
"""
import os
import argparse
import pandas as pd
import numpy as np
import joblib
import json
from features import build_feature_frame, HOLIDAYS
from train_model import FEATURE_COLS

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))


def load_models():
    models = {
        0.1: joblib.load(os.path.join(MODEL_DIR, "model_p10.pkl")),
        0.5: joblib.load(os.path.join(MODEL_DIR, "model_p50.pkl")),
        0.9: joblib.load(os.path.join(MODEL_DIR, "model_p90.pkl")),
    }
    with open(os.path.join(MODEL_DIR, "model_metadata.json")) as f:
        meta = json.load(f)
    return models, meta


def recursive_forecast(df, models, sku_id, horizon_days=7):
    """
    Walk forward one day at a time. Each day's median (p50) prediction is
    appended to the SKU's demand history so the NEXT day's lag/rolling
    features are computed from real history + prior predictions, not a
    single static snapshot.
    """
    sku_rows = df[df["product_id"] == sku_id].sort_values("date").copy()
    if sku_rows.empty:
        raise ValueError(f"No data for SKU {sku_id}")

    # working history of units_sold we can append predictions to
    history = sku_rows[["date", "units_sold"]].copy()
    static = sku_rows.iloc[-1]  # last known static attributes (category, city, price, etc.)
    last_date = sku_rows["date"].max()

    results = []
    for step in range(1, horizon_days + 1):
        next_date = last_date + pd.Timedelta(days=step)

        # --- rebuild lag/rolling features from the (growing) history series ---
        h = history["units_sold"]
        lag_1 = h.iloc[-1]
        lag_7 = h.iloc[-7] if len(h) >= 7 else h.mean()
        lag_14 = h.iloc[-14] if len(h) >= 14 else h.mean()
        lag_28 = h.iloc[-28] if len(h) >= 28 else h.mean()
        roll_mean_7 = h.tail(7).mean()
        roll_std_7 = h.tail(7).std()
        roll_mean_14 = h.tail(14).mean()
        roll_std_14 = h.tail(14).std()
        roll_mean_28 = h.tail(28).mean()
        roll_std_28 = h.tail(28).std()

        # --- holiday/calendar proximity features (mirrors features.py logic) ---
        next_date_norm = pd.Timestamp(next_date).normalize()
        holidays_sorted = sorted(HOLIDAYS)
        is_holiday = int(next_date_norm in set(holidays_sorted))
        future_holidays = [h for h in holidays_sorted if h >= next_date_norm]
        past_holidays = [h for h in holidays_sorted if h <= next_date_norm]
        days_to_next_holiday = (future_holidays[0] - next_date_norm).days if future_holidays else 365
        days_since_prev_holiday = (next_date_norm - past_holidays[-1]).days if past_holidays else 365
        is_near_holiday = int(days_to_next_holiday <= 3 or days_since_prev_holiday <= 1)

        row = {
            "day_of_week": next_date.dayofweek,
            "is_weekend": int(next_date.dayofweek in [5, 6]),
            "month": next_date.month,
            "day_of_month": next_date.day,
            "week_of_year": int(next_date.isocalendar().week),
            "is_holiday": is_holiday,
            "days_to_next_holiday": days_to_next_holiday,
            "days_since_prev_holiday": days_since_prev_holiday,
            "is_near_holiday": is_near_holiday,
            "lag_1": lag_1, "lag_7": lag_7, "lag_14": lag_14, "lag_28": lag_28,
            "roll_mean_7": roll_mean_7, "roll_std_7": roll_std_7,
            "roll_mean_14": roll_mean_14, "roll_std_14": roll_std_14,
            "roll_mean_28": roll_mean_28, "roll_std_28": roll_std_28,
            # static / carried-forward attributes: no known future promo -> assume off
            "price": static["price"], "discount_pct": 0, "promotion_flag": 0,
            "is_organic": static["is_organic"], "shelf_life_days": static["shelf_life_days"],
            "weight_g": static["weight_g"],
            "category": static["category"], "city": static["city"],
            "warehouse_id": static["warehouse_id"], "product_id_cat": static["product_id_cat"],
        }
        X = pd.DataFrame([row])
        for col in ["category", "city", "warehouse_id", "product_id_cat"]:
            X[col] = X[col].astype("category")

        p10 = max(0.0, models[0.1].predict(X)[0])
        p50 = max(0.0, models[0.5].predict(X)[0])
        p90 = max(0.0, models[0.9].predict(X)[0])
        p10, p90 = min(p10, p50), max(p90, p50)

        results.append({
            "date": next_date, "forecast_p10": round(p10, 1),
            "forecast_p50": round(p50, 1), "forecast_p90": round(p90, 1),
        })

        # feed this day's median prediction forward as the new "actual" for next iteration
        history = pd.concat([history, pd.DataFrame([{"date": next_date, "units_sold": p50}])], ignore_index=True)

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
    print(f"\nRecursive forecast for SKU {args.sku} ({sku_name}), next {args.days} days:")

    forecast = recursive_forecast(df, models, args.sku, args.days)
    print(forecast.to_string(index=False))
