"""
Feature engineering for the quick-commerce dataset
(quick_commerce_with_events_clean.csv) -- the project's chosen production
dataset. Mirrors the M5 pipeline's structure (same lag/rolling/calendar
feature shapes) but uses REAL fields this dataset provides instead of the
proxies M5 forced us to approximate:

  - promotion_flag, discount_pct are given directly (M5 needed a
    price-vs-trailing-average proxy for this).
  - stock_on_hand is given directly -> real stockout censoring is possible
    here (M5 had no inventory field at all, a limitation we had to flag).
  - event_name_1 / event_type_1 are the Indian holiday calendar we merged
    in (add_indian_calendar.py), built the same way as M5's own event
    columns so the holiday feature logic is unchanged.
"""
import pandas as pd

from app.core.config import settings


def load_data(path=None):
    path = path or settings.dataset_path
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values(["product_id", "warehouse_id", "date"]).reset_index(drop=True)
    return df


def add_calendar_features(df):
    df["day_of_week"] = df["date"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["month"] = df["date"].dt.month
    df["day_of_month"] = df["date"].dt.day
    df["week_of_year"] = df["date"].dt.isocalendar().week.astype(int)
    return df


def add_holiday_features(df):
    df["is_holiday"] = (df["event_name_1"] != "No Event").astype(int)
    return df


def add_stock_features(df):
    """Real stock_on_hand lets us do what M5 couldn't: flag stockout days
    so the model isn't trained to believe demand was truly zero when the
    shelf was simply empty."""
    df["is_stockout"] = (df["stock_on_hand"] <= 0).astype(int)
    # days of cover: how many days current stock would last at recent sell-through
    return df


def add_lag_and_rolling_features(df):
    g = df.groupby(["product_id", "warehouse_id"])["units_sold"]
    for lag in [1, 7, 14, 28]:
        df[f"lag_{lag}"] = g.shift(lag)
    for window in [7, 14, 28]:
        shifted = g.shift(1)
        df[f"roll_mean_{window}"] = shifted.groupby([df["product_id"], df["warehouse_id"]]).transform(
            lambda s: s.rolling(window, min_periods=max(3, window // 3)).mean()
        )
        df[f"roll_std_{window}"] = shifted.groupby([df["product_id"], df["warehouse_id"]]).transform(
            lambda s: s.rolling(window, min_periods=max(3, window // 3)).std()
        )
    return df


def encode_categoricals(df):
    df["is_organic_flag"] = df["is_organic"].astype(int)
    for col in ["category", "warehouse_id", "product_id", "city", "event_type_1"]:
        df[col + "_cat"] = df[col].astype("category")
    return df


def build_feature_frame(path=None):
    df = load_data(path)
    df = add_calendar_features(df)
    df = add_holiday_features(df)
    df = add_stock_features(df)
    df = add_lag_and_rolling_features(df)
    df = encode_categoricals(df)
    return df
