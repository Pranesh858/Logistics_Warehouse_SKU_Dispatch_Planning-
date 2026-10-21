"""Retrain the demand model on an uploaded dataset plus the history it already knows.

Flow (used by the dataset upload in the forecast module):
  1. validate_upload   - check columns and values, fill the optional columns, report problems
  2. merge_history     - old rows + new rows, a new row replaces an old one for the same SKU, warehouse and day
  3. retrain           - fit a candidate model on the merged data, score it against the current model on the same
                         recent days, and only replace the current model when it is not clearly worse
  4. promote           - back up the old model and dataset, write the new ones, reload the in-memory copies
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from app.core.config import settings
from app.ml.features import (
    add_calendar_features, add_holiday_features, add_lag_and_rolling_features, add_stock_features,
    encode_categoricals,
)

FEATURE_COLS = [
    "day_of_week", "is_weekend", "month", "day_of_month", "week_of_year",
    "is_holiday",
    "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_mean_7", "roll_std_7", "roll_mean_14", "roll_std_14", "roll_mean_28", "roll_std_28",
    "price", "discount_pct", "promotion_flag",
    "is_organic_flag", "shelf_life_days", "weight_g",
    "category_cat", "warehouse_id_cat", "product_id_cat", "city_cat", "event_type_1_cat",
]
CAT_COLS = ["category_cat", "warehouse_id_cat", "product_id_cat", "city_cat", "event_type_1_cat"]
TARGET = "units_sold"
KEYS = ["product_id", "warehouse_id"]

REQUIRED = ["product_id", "warehouse_id", "date", "units_sold", "stock_on_hand", "price", "category", "city"]
DEFAULTS = {
    "product_name": None, "discount_pct": 0, "promotion_flag": 0, "is_organic": False,
    "shelf_life_days": None, "weight_g": None, "event_name_1": "No Event", "event_type_1": "No Event",
}
ALL_COLUMNS = ["product_id", "product_name", "category", "date", "units_sold", "stock_on_hand", "price",
               "discount_pct", "promotion_flag", "city", "warehouse_id", "is_organic", "shelf_life_days",
               "weight_g", "event_name_1", "event_type_1"]

MIN_DAYS_PER_SKU = 35          # lags reach back 28 days, so a series needs a little more than that
HOLDOUT_DAYS = 28
MAX_WAPE_WORSENING = 0.10      # promote unless the new model is more than 10% worse (relative)


class UploadError(ValueError):
    """The uploaded file cannot be used; the message says why in plain words."""


def wape(y_true, y_pred) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    denom = np.abs(y_true).sum()
    return float(np.abs(y_true - y_pred).sum() / denom) if denom else 0.0


def mape(y_true, y_pred, eps=1e-6) -> float:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    mask = y_true > eps
    return float((np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]).mean() * 100) if mask.any() else 0.0


# ---------------------------------------------------------------- validation
def validate_upload(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Returns (clean rows, blocking problems, warnings). Blocking problems mean the file is refused."""
    errors: list[str] = []
    warnings: list[str] = []
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return df, [f"Missing column(s): {', '.join(missing)}. Required: {', '.join(REQUIRED)}."], []
    if df.empty:
        return df, ["The file has no rows."], []

    for col in ("units_sold", "stock_on_hand", "price", "product_id"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_rows = df[REQUIRED].isna().any(axis=1) | df["warehouse_id"].astype(str).str.strip().eq("")
    if bad_rows.any():
        warnings.append(f"{int(bad_rows.sum())} row(s) with a blank or unreadable required value were skipped.")
        df = df[~bad_rows].copy()
    if df.empty:
        return df, ["No usable rows are left after removing unreadable ones."], warnings

    df["product_id"] = df["product_id"].astype(int)
    df["warehouse_id"] = df["warehouse_id"].astype(str).str.strip().str.upper()
    for col in ("category", "city"):
        df[col] = df[col].astype(str).str.strip()

    if (df["units_sold"] < 0).any():
        errors.append(f"units_sold has {int((df['units_sold'] < 0).sum())} negative value(s).")
    if (df["stock_on_hand"] < 0).any():
        errors.append(f"stock_on_hand has {int((df['stock_on_hand'] < 0).sum())} negative value(s).")
    if (df["price"] <= 0).any():
        errors.append(f"price must be above zero ({int((df['price'] <= 0).sum())} row(s) are not).")

    for col, default in DEFAULTS.items():
        if col not in df.columns:
            df[col] = default
    df["discount_pct"] = pd.to_numeric(df["discount_pct"], errors="coerce").fillna(0)
    if ((df["discount_pct"] < 0) | (df["discount_pct"] > 100)).any():
        errors.append("discount_pct must be between 0 and 100.")
    df["promotion_flag"] = pd.to_numeric(df["promotion_flag"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    df["is_organic"] = df["is_organic"].astype(str).str.lower().isin(["true", "1", "yes"])
    for col in ("event_name_1", "event_type_1"):
        df[col] = df[col].fillna("No Event").astype(str)
    if df["product_name"].isna().all():
        df["product_name"] = "SKU " + df["product_id"].astype(str)
    df["product_name"] = df["product_name"].fillna("SKU " + df["product_id"].astype(str))

    dup = df.duplicated(KEYS + ["date"], keep="last")
    if dup.any():
        warnings.append(f"{int(dup.sum())} duplicate row(s) for the same SKU, warehouse and day; the last one was kept.")
        df = df[~dup]

    if errors:
        return df, errors, warnings
    return df[ALL_COLUMNS].copy(), errors, warnings


def _fill_sku_attributes(df: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """shelf_life_days and weight_g are SKU properties: take them from the existing data when the upload has none."""
    out = df.copy()
    for col in ("shelf_life_days", "weight_g"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
        known = reference.groupby("product_id")[col].first() if col in reference.columns else pd.Series(dtype=float)
        out[col] = out[col].fillna(out["product_id"].map(known))
        out[col] = out[col].fillna(float(pd.to_numeric(reference[col], errors="coerce").median()) if col in reference.columns else 0.0)
    return out


def summarize_upload(new: pd.DataFrame, old_raw: pd.DataFrame) -> dict:
    old_skus = set(map(tuple, old_raw[KEYS].drop_duplicates().to_numpy()))
    new_pairs = new[KEYS].drop_duplicates()
    fresh = [p for p in map(tuple, new_pairs.to_numpy()) if p not in old_skus]
    new_products = sorted(set(new["product_id"]) - set(old_raw["product_id"]))
    days = new.groupby(KEYS)["date"].nunique()
    short = days[days < MIN_DAYS_PER_SKU]
    # a new series needs enough days by itself; an existing one borrows its older history
    too_short = [k for k in fresh if k in set(short.index)]
    old_last = old_raw["date"].max()
    return {
        "rows": int(len(new)),
        "date_from": new["date"].min().strftime("%Y-%m-%d"),
        "date_to": new["date"].max().strftime("%Y-%m-%d"),
        "skus": int(len(new_pairs)),
        "new_product_ids": [int(p) for p in new_products],
        "new_sku_warehouse_pairs": len(fresh),
        "short_history_pairs": [{"product_id": int(p), "warehouse_id": w} for p, w in too_short],
        "overlap_rows": int(new.merge(old_raw[KEYS + ["date"]], on=KEYS + ["date"]).shape[0]),
        "extends_history": bool(new["date"].max() > old_last),
        "current_history_to": old_last.strftime("%Y-%m-%d"),
    }


# -------------------------------------------------------------------- merging
def merge_history(old_raw: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[int, str]]]:
    """Old plus new rows. Series that would still be too short to forecast are left out and returned."""
    new = _fill_sku_attributes(new, old_raw)
    merged = pd.concat([old_raw[ALL_COLUMNS], new[ALL_COLUMNS]], ignore_index=True)
    merged = merged.drop_duplicates(KEYS + ["date"], keep="last")
    sizes = merged.groupby(KEYS)["date"].nunique()
    short = sizes[sizes < MIN_DAYS_PER_SKU]
    dropped = [(int(p), str(w)) for p, w in short.index]
    if dropped:
        merged = merged.merge(short.rename("n").reset_index(), on=KEYS, how="left")
        merged = merged[merged["n"].isna()].drop(columns="n")
    return merged.sort_values(KEYS + ["date"]).reset_index(drop=True), dropped


def features_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.sort_values(KEYS + ["date"]).reset_index(drop=True).copy()
    df = add_calendar_features(df)
    df = add_holiday_features(df)
    df = add_stock_features(df)
    df = add_lag_and_rolling_features(df)
    return encode_categoricals(df)


def prepare_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with enough history; days the shelf was empty are left out (sales then say nothing about demand)."""
    trainable = df.dropna(subset=["lag_28", "roll_mean_28"])
    return trainable[trainable["is_stockout"] == 0].copy()


def _params() -> dict:
    return dict(objective="tweedie", tweedie_variance_power=1.1, n_estimators=settings.retrain_estimators,
                learning_rate=0.05, num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1)


def fit(frame: pd.DataFrame) -> lgb.LGBMRegressor:
    train = prepare_dataset(frame)
    model = lgb.LGBMRegressor(**_params())
    model.fit(train[FEATURE_COLS], train[TARGET], categorical_feature=CAT_COLS)
    return model


def holdout_score(raw: pd.DataFrame, cutoff: pd.Timestamp, pairs: set | None = None) -> tuple[float, int]:
    """Train on rows up to `cutoff`, then predict the days after it with the true lags (one day ahead)."""
    frame = features_from_raw(raw)
    model = fit(frame[frame["date"] <= cutoff])
    test = prepare_dataset(frame[frame["date"] > cutoff])
    if pairs is not None:
        test = test[[(p, w) in pairs for p, w in zip(test["product_id"], test["warehouse_id"])]]
    if test.empty:
        return float("nan"), 0
    pred = np.clip(model.predict(test[FEATURE_COLS]), 0, None)
    return wape(test[TARGET], pred), len(test)


def compare_models(old_raw: pd.DataFrame, merged: pd.DataFrame) -> dict:
    """Same recent days, same SKUs: the model trained on the old data alone vs the one trained on the merged data."""
    cutoff = old_raw["date"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    pairs = set(map(tuple, old_raw[KEYS].drop_duplicates().to_numpy()))
    before, n_before = holdout_score(old_raw, cutoff, pairs)
    after, n_after = holdout_score(merged, cutoff, pairs)
    worse = bool(np.isfinite(before) and np.isfinite(after) and after > before * (1 + MAX_WAPE_WORSENING))
    return {"holdout_days": HOLDOUT_DAYS, "rows_scored": n_after, "wape_before": round(before, 4),
            "wape_after": round(after, 4), "worse": worse,
            "change_pct": round((after - before) / before * 100, 1) if before else 0.0}


# ------------------------------------------------------------------ promotion
def backup_dir() -> Path:
    d = Path(settings.model_path).parent / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def promote(model, merged_raw: pd.DataFrame, frame: pd.DataFrame, comparison: dict) -> str:
    """Back up what is live, then write the new model, metadata and dataset."""
    dest = backup_dir()
    for p in (settings.model_path, settings.model_metadata_path, settings.dataset_path):
        if Path(p).exists():
            shutil.copy2(p, dest / Path(p).name)

    meta = json.loads(Path(settings.model_metadata_path).read_text(encoding="utf-8"))
    train = prepare_dataset(frame)
    meta.update({
        "training_rows": int(len(train)),
        "training_date_range": [frame["date"].min().strftime("%Y-%m-%d"), frame["date"].max().strftime("%Y-%m-%d")],
        "products": int(frame["product_id"].nunique()),
        "warehouses": int(frame["warehouse_id"].nunique()),
        "cities": int(frame["city"].nunique()),
        "stockout_rows_excluded": int((frame.dropna(subset=["lag_28", "roll_mean_28"])["is_stockout"] == 1).sum()),
        "retrained_at": datetime.now().isoformat(timespec="seconds"),
        "retrain_check": comparison,
    })
    if np.isfinite(comparison.get("wape_after", float("nan"))):
        meta["cv_metrics"] = {"avg_wape": comparison["wape_after"], "avg_mape_pct": meta.get("cv_metrics", {}).get("avg_mape_pct", 0)}

    joblib.dump(model, settings.model_path)
    Path(settings.model_metadata_path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    out = merged_raw.copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out.to_csv(settings.dataset_path, index=False)
    return str(dest)


def rollback(backup: str) -> None:
    src = Path(backup)
    for p in (settings.model_path, settings.model_metadata_path, settings.dataset_path):
        if (src / Path(p).name).exists():
            shutil.copy2(src / Path(p).name, p)
