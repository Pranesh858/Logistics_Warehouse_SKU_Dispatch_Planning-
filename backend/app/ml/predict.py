"""Recursive multi-day forecast with the trained LightGBM model (ported from qc_predict_final.py)."""
import json
import joblib
import numpy as np
import pandas as pd

from app.core.config import settings
from app.ml import calendar
from app.ml.features import build_feature_frame, add_lag_and_rolling_features

def load_model(model_path=None, metadata_path=None):
    model_path = model_path or settings.model_path
    metadata_path = metadata_path or settings.model_metadata_path
    model = joblib.load(model_path)
    with open(metadata_path) as f:
        meta = json.load(f)
    return model, meta


# lag_28 plus the 28-day rolling window's shift(1) reach back 29 rows; the rest is headroom.
LOOKBACK_DAYS = 40


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

    # The longest lookback any feature has is lag_28, and roll_*_28 is shift(1) over 28 days, so a new row can
    # reach back 29 rows at most. Older rows cannot change a single number, yet the loop below rebuilds every
    # lag and rolling average over whatever it is given, once per forecast day. Keeping only the window the
    # features can actually see makes the result identical and the work far smaller.
    history = df.groupby(["product_id", "warehouse_id"], as_index=False, group_keys=False).tail(LOOKBACK_DAYS).copy()
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

        # What is genuinely knowable about this day. Festivals are in the calendar, so the model is told about
        # them instead of being shown an ordinary Tuesday. Both the flag and the event type are set: leaving the
        # type carried over from the last row of history contradicted the flag whenever the data ended on a
        # festival. Promotions stay at zero because no future promotion plan is fed in; that remains a stated
        # limitation rather than a guess.
        event = calendar.lookup([target_date], history=df)[0]
        latest["is_holiday"] = event["is_holiday"]
        latest["event_type_1"] = event["type"]
        if "event_type_1_cat" in latest.columns:
            latest["event_type_1_cat"] = pd.Categorical([event["type"]] * len(latest),
                                                        categories=df["event_type_1_cat"].cat.categories)
        if "event_name_1" in latest.columns:
            latest["event_name_1"] = event["name"]
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
