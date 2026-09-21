"""
Aggregates day-by-day forecasts (from batch_forecast.py) into period totals
(e.g., monthly) per SKU -- what a manager actually wants to see for stock
planning, rather than a row per day.

Uncertainty note: simply summing p10/p90 across days would OVERSTATE the
combined uncertainty, since daily forecast errors are not perfectly
correlated (a high-error day and a low-error day partly cancel out in a
total). We instead approximate each day's standard deviation from its
p10/p90 band, combine variances assuming rough independence across days,
and reconstruct a proper p10/p50/p90 for the TOTAL.
"""
import argparse
import pandas as pd
import numpy as np

# z-score such that P(-z < Z < z) = 0.80 for a standard normal -> 1.2816
Z_80 = 1.2816


def aggregate_forecast(df):
    """df: columns [product_id, date, forecast_p10, forecast_p50, forecast_p90]
    Returns one row per product_id with the SUMMED p50 and a properly
    combined p10/p90 for the whole period."""
    df = df.copy()
    df["daily_sigma"] = (df["forecast_p90"] - df["forecast_p10"]) / (2 * Z_80)

    grouped = df.groupby("product_id").agg(
        total_forecast=("forecast_p50", "sum"),
        combined_variance=("daily_sigma", lambda s: np.sum(s ** 2)),
        n_days=("date", "count"),
        period_start=("date", "min"),
        period_end=("date", "max"),
    ).reset_index()

    grouped["combined_sigma"] = np.sqrt(grouped["combined_variance"])
    grouped["total_p10"] = np.clip(grouped["total_forecast"] - Z_80 * grouped["combined_sigma"], 0, None)
    grouped["total_p90"] = grouped["total_forecast"] + Z_80 * grouped["combined_sigma"]

    return grouped[["product_id", "period_start", "period_end", "n_days",
                     "total_p10", "total_forecast", "total_p90"]].rename(
        columns={"total_forecast": "total_p50"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="forecast_all_skus.csv",
                         help="Daily forecast CSV from batch_forecast.py")
    parser.add_argument("--out", type=str, default="forecast_monthly_totals.csv")
    args = parser.parse_args()

    daily = pd.read_csv(args.input, parse_dates=["date"])
    print(f"Loaded {len(daily)} daily forecast rows across {daily['product_id'].nunique()} SKUs")

    monthly = aggregate_forecast(daily)
    numeric_cols = ["total_p10", "total_p50", "total_p90"]
    monthly[numeric_cols] = monthly[numeric_cols].round(1)
    monthly.to_csv(args.out, index=False)

    print(f"\nSaved: {args.out}")
    print(f"\nPreview (first 10 SKUs):")
    print(monthly.head(10).to_string(index=False))
