"""
Feature engineering pipeline for SKU demand forecasting.
Global model approach: one LightGBM model trained across all SKUs.
"""
import os
import pandas as pd
import numpy as np

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Sample dataset.csv")

# Illustrative India-relevant holiday/festival calendar (2023-2026).
# Dates are approximate for lunar-calendar festivals (Holi, Diwali) and should
# be confirmed against an authoritative calendar before production use.
HOLIDAYS = pd.to_datetime([
    "2023-01-01", "2023-01-26", "2023-03-08", "2023-08-15", "2023-10-02",
    "2023-11-12", "2023-12-25",
    "2024-01-01", "2024-01-26", "2024-03-25", "2024-08-15", "2024-10-02",
    "2024-11-01", "2024-12-25",
    "2025-01-01", "2025-01-26", "2025-03-14", "2025-08-15", "2025-10-02",
    "2025-10-20", "2025-12-25",
    "2026-01-01", "2026-01-26", "2026-03-04", "2026-08-15", "2026-10-02",
    "2026-11-08", "2026-12-25",
])

def load_data():
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values(["product_id", "date"]).reset_index(drop=True)
    return df

def handle_stockout_censoring(df):
    """
    Demand is censored (undercounted) on stockout days — units_sold reflects
    what COULD be sold, not true demand. We flag these days and exclude them
    from training targets (can't trust the label), but keep them as history
    for computing lag/rolling features on other days.
    """
    df["is_stockout"] = (df["stock_on_hand"] == 0).astype(int)
    return df

def handle_missing(df):
    # forward-fill within each SKU for price/stock; units_sold missing -> treat as unknown, will be excluded from training
    df["units_sold_raw"] = df["units_sold"]
    df["price"] = df.groupby("product_id")["price"].transform(lambda s: s.ffill().bfill())
    df["stock_on_hand"] = df.groupby("product_id")["stock_on_hand"].transform(lambda s: s.ffill().bfill())
    return df

def add_calendar_features(df):
    df["day_of_week"] = df["date"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["month"] = df["date"].dt.month
    df["day_of_month"] = df["date"].dt.day
    df["week_of_year"] = df["date"].dt.isocalendar().week.astype(int)
    df["year"] = df["date"].dt.year
    return df

def add_holiday_features(df):
    """Holiday/festival features: proximity to a named holiday tends to
    correlate with demand spikes (independent of the promotion_flag signal)."""
    holiday_set = set(HOLIDAYS)
    df["is_holiday"] = df["date"].isin(holiday_set).astype(int)

    holiday_arr = np.array(sorted(HOLIDAYS))
    dates_arr = df["date"].values.astype("datetime64[D]")
    holiday_arr_d = holiday_arr.astype("datetime64[D]")
    idx = np.searchsorted(holiday_arr_d, dates_arr)
    idx_clipped_hi = np.clip(idx, 0, len(holiday_arr_d) - 1)
    idx_clipped_lo = np.clip(idx - 1, 0, len(holiday_arr_d) - 1)
    days_to_next = (holiday_arr_d[idx_clipped_hi] - dates_arr).astype("timedelta64[D]").astype(int)
    days_since_prev = (dates_arr - holiday_arr_d[idx_clipped_lo]).astype("timedelta64[D]").astype(int)
    df["days_to_next_holiday"] = np.clip(days_to_next, 0, 365)
    df["days_since_prev_holiday"] = np.clip(days_since_prev, 0, 365)
    df["is_near_holiday"] = ((df["days_to_next_holiday"] <= 3) | (df["days_since_prev_holiday"] <= 1)).astype(int)
    return df

def add_lag_and_rolling_features(df):
    """Lag and rolling features computed per-SKU, using units_sold (raw, with NaNs
    left as-is so rolling windows don't fabricate data across stockout gaps)."""
    df = df.sort_values(["product_id", "date"])
    grp = df.groupby("product_id")["units_sold"]

    for lag in [1, 7, 14, 28]:
        df[f"lag_{lag}"] = grp.shift(lag)

    for window in [7, 14, 28]:
        df[f"roll_mean_{window}"] = grp.transform(
            lambda s: s.shift(1).rolling(window, min_periods=max(2, window // 3)).mean()
        )
        df[f"roll_std_{window}"] = grp.transform(
            lambda s: s.shift(1).rolling(window, min_periods=max(2, window // 3)).std()
        )
    return df

def encode_categoricals(df):
    for col in ["category", "city", "warehouse_id"]:
        df[col] = df[col].astype("category")
    df["is_organic"] = df["is_organic"].astype(int)
    df["product_id_cat"] = df["product_id"].astype("category")
    return df

def build_feature_frame():
    df = load_data()
    df = handle_stockout_censoring(df)
    df = handle_missing(df)
    df = add_calendar_features(df)
    df = add_holiday_features(df)
    df = add_lag_and_rolling_features(df)
    df = encode_categoricals(df)
    return df

if __name__ == "__main__":
    df = build_feature_frame()
    print("Shape:", df.shape)
    print("\nColumns:", list(df.columns))
    print("\nSample feature row:")
    print(df[df["product_id"] == 1].iloc[50][
        ["date", "units_sold", "is_stockout", "lag_1", "lag_7", "roll_mean_7", "roll_std_7", "day_of_week", "promotion_flag"]
    ])
    print("\nNaN counts in key features (expected early in each SKU's series):")
    print(df[["lag_1", "lag_7", "lag_28", "roll_mean_28"]].isna().sum())
    df.to_pickle("/home/claude/forecast/features.pkl")
    print("\nSaved features.pkl")
