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
import sys
from pathlib import Path

import pandas as pd

from app.core.config import settings

_sample_notice_shown = False


def resolve_dataset_path(path=None) -> Path:
    """Where to read the sales history from: the full file if it is there, else the sample in the repo.

    The full history is ~37 MB and deliberately kept out of git, so a fresh clone does not have it. Falling
    back to the committed sample means the project starts straight after cloning instead of dying at startup
    on a missing file. Writers still write to `settings.dataset_path`, so the first merge promotes the
    history to the full path.
    """
    if path:
        return Path(path)
    full = Path(settings.dataset_path)
    if full.exists():
        return full
    sample = Path(settings.sample_dataset_path)
    if sample.exists():
        return sample
    raise FileNotFoundError(
        "No sales history found.\n"
        f"  Looked for the full history at: {full}\n"
        f"  and the bundled sample at:      {sample}\n\n"
        "The full history is not committed to git. Copy quick_commerce_with_events_clean.csv into "
        f"{full.parent}, or point DATASET_PATH in .env at wherever you keep it. "
        "See README, section 'Sales history'."
    )


def using_sample_dataset() -> bool:
    """True when the forecast is reading the bundled 120-day sample instead of the full history."""
    return not Path(settings.dataset_path).exists() and Path(settings.sample_dataset_path).exists()


def read_history() -> pd.DataFrame:
    """The sales history as it stands, for code that merges into it (uploads, retrains, the ERP sales feed).

    Reads the sample when the full file is missing, like the forecast does. What these callers write always goes
    to `settings.dataset_path`, so on a fresh clone the first upload or retrain turns sample + new rows into the
    history from then on.
    """
    return pd.read_csv(resolve_dataset_path(), parse_dates=["date"])


def load_data(path=None):
    global _sample_notice_shown
    resolved = resolve_dataset_path(path)
    if path is None and using_sample_dataset() and not _sample_notice_shown:
        _sample_notice_shown = True
        print(f"[data] Full sales history not found; reading the bundled sample {resolved.name} "
              f"(300 SKUs x 6 warehouses, 120 days). Forecasts and KPIs cover that window only. "
              f"Put quick_commerce_with_events_clean.csv in {resolved.parent} for the full three years.",
              file=sys.stderr, flush=True)
    df = pd.read_csv(resolved, parse_dates=["date"])
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
    """Lags and rolling statistics per SKU x warehouse.

    The rolling windows go through `groupby(...).rolling(...)` rather than `transform(lambda s: s.rolling(...))`.
    They compute the same numbers, but the lambda form makes pandas fall back to a per-group Python loop that
    rebuilds an index for every one of the ~1,800 groups, every time this is called. The recursive forecast calls
    it once per day ahead, which is where nearly all of its time was going.
    """
    df = df.sort_values(["product_id", "warehouse_id", "date"])
    g = df.groupby(["product_id", "warehouse_id"], sort=False)["units_sold"]
    for lag in [1, 7, 14, 28]:
        df[f"lag_{lag}"] = g.shift(lag)

    shifted = g.shift(1)                       # yesterday backwards: today's sale never feeds its own average
    grouped = shifted.groupby([df["product_id"], df["warehouse_id"]], sort=False)
    for window in [7, 14, 28]:
        min_periods = max(3, window // 3)
        stats = grouped.rolling(window, min_periods=min_periods).agg(["mean", "std"])
        stats = stats.reset_index(level=[0, 1], drop=True)
        df[f"roll_mean_{window}"] = stats["mean"]
        df[f"roll_std_{window}"] = stats["std"]
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
