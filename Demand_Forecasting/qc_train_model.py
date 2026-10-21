"""
Global LightGBM demand forecasting model, trained on the quick-commerce
dataset -- the project's chosen production dataset. Same validated
methodology as the M5 pipeline:
  - One pooled model across all 300 SKUs / 6 warehouses
  - Rolling-origin CV (time-respecting, no random split)
  - WAPE / MAPE on held-out future windows
  - Tweedie objective (the variant that won on M5's CV comparison)

Real improvement over the M5 pipeline: this dataset has stock_on_hand, so
stockout days (shelf genuinely empty) are excluded from training -- the
model is never taught that demand was zero when it was actually just
unavailable to buy. M5 could not do this; it's a real limitation we flagged
there and fixed here.
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
from qc_features import build_feature_frame

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


def prepare_dataset(df):
    """Drop rows with insufficient lag/rolling history, AND exclude stockout
    days from training -- real stockout censoring, which M5 could not do."""
    trainable = df.dropna(subset=["lag_28", "roll_mean_28"]).copy()
    before = len(trainable)
    trainable = trainable[trainable["is_stockout"] == 0].copy()
    print(f"Excluded {before - len(trainable):,} stockout-day rows from training "
          f"(real censoring, not possible with M5)")
    return trainable


def rolling_origin_splits(df, n_folds=3, test_days=30):
    dates = sorted(df["date"].unique())
    max_date = dates[-1]
    splits = []
    for fold in range(n_folds, 0, -1):
        test_end = max_date - pd.Timedelta(days=test_days * (fold - 1))
        test_start = test_end - pd.Timedelta(days=test_days)
        train_end = test_start
        train_idx = df[df["date"] < train_end].index
        test_idx = df[(df["date"] >= test_start) & (df["date"] < test_end)].index
        if len(train_idx) > 1000 and len(test_idx) > 100:
            splits.append((train_idx, test_idx))
    return splits


def wape(y_true, y_pred):
    return np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true))


def mape(y_true, y_pred, eps=1e-6):
    mask = y_true > eps
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100


def train_and_evaluate():
    print("Building feature frame from quick-commerce data...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)
    print(f"Trainable rows: {len(trainable):,} of {len(df):,} total")

    splits = rolling_origin_splits(trainable, n_folds=3, test_days=30)
    print(f"Rolling-origin CV folds: {len(splits)}")

    params = dict(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1,
    )

    fold_metrics = []
    for i, (train_idx, test_idx) in enumerate(splits):
        train = trainable.loc[train_idx]
        test = trainable.loc[test_idx]

        X_train, y_train = train[FEATURE_COLS], train[TARGET]
        X_test, y_test = test[FEATURE_COLS], test[TARGET]

        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train, categorical_feature=CAT_COLS)
        preds = np.clip(model.predict(X_test), 0, None)

        fold_wape = wape(y_test.values, preds)
        fold_mape = mape(y_test.values, preds)
        fold_metrics.append({"fold": i + 1, "wape": fold_wape, "mape": fold_mape, "n_test": len(test)})
        print(f"Fold {i+1}: WAPE={fold_wape:.3f}  MAPE={fold_mape:.1f}%  (n={len(test):,})")

    return fold_metrics, trainable, model


def train_final_model():
    print("Building feature frame from quick-commerce data...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)

    params = dict(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1,
    )
    X, y = trainable[FEATURE_COLS], trainable[TARGET]
    model = lgb.LGBMRegressor(**params)
    model.fit(X, y, categorical_feature=CAT_COLS)
    print(f"Final model trained on {len(trainable):,} rows (full history).")
    return model, trainable


if __name__ == "__main__":
    metrics, trainable, last_model = train_and_evaluate()
    print("\n=== Summary across folds (quick-commerce data, Tweedie objective) ===")
    avg_wape = np.mean([m["wape"] for m in metrics])
    avg_mape = np.mean([m["mape"] for m in metrics])
    print(f"Average WAPE: {avg_wape:.3f}")
    print(f"Average MAPE: {avg_mape:.1f}%")
    print(f"\nKPI target (BRD): MAPE <= 15-20%  ->  "
          f"{'MEETS TARGET' if avg_mape <= 20 else 'ABOVE TARGET'}")
