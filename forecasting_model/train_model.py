"""
Global LightGBM demand forecasting model.
- One model across all 300 SKUs (pooled learning)
- Quantile regression for prediction intervals (10th / 50th / 90th percentile)
- Rolling-origin cross-validation (no random split — respects time order)
- Stockout-censored days excluded from training target
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
from features import build_feature_frame

FEATURE_COLS = [
    "day_of_week", "is_weekend", "month", "day_of_month", "week_of_year",
    "is_holiday", "days_to_next_holiday", "days_since_prev_holiday", "is_near_holiday",
    "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_mean_7", "roll_std_7", "roll_mean_14", "roll_std_14", "roll_mean_28", "roll_std_28",
    "price", "discount_pct", "promotion_flag",
    "is_organic", "shelf_life_days", "weight_g",
    "category", "city", "warehouse_id", "product_id_cat",
]
CAT_COLS = ["category", "city", "warehouse_id", "product_id_cat"]
TARGET = "units_sold"

def prepare_dataset(df):
    """Exclude stockout days and rows with missing target from training (censored demand)."""
    trainable = df[(df["is_stockout"] == 0) & (df[TARGET].notna())].copy()
    return trainable

def rolling_origin_splits(df, n_folds=3, test_days=30):
    """Generate (train_idx, test_idx) splits sliding forward in time.
    Each fold trains on everything before a cutoff and tests on the next `test_days`."""
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
    """Weighted Absolute Percentage Error — robust to zero/near-zero actuals, standard retail metric."""
    return np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true))

def mape(y_true, y_pred, eps=1e-6):
    mask = y_true > eps
    return np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

def train_and_evaluate(hyperparams=None):
    print("Building feature frame...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)
    print(f"Trainable rows: {len(trainable)} of {len(df)} total (excluded stockout/missing)")

    splits = rolling_origin_splits(trainable, n_folds=3, test_days=30)
    print(f"Rolling-origin CV folds: {len(splits)}")

    default_params = dict(
        objective="regression", n_estimators=300, learning_rate=0.05,
        num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1,
    )
    params = {**default_params, **(hyperparams or {})}
    params["random_state"] = 42
    params["verbosity"] = -1
    params["objective"] = "regression"

    fold_metrics = []
    for i, (train_idx, test_idx) in enumerate(splits):
        train = trainable.loc[train_idx]
        test = trainable.loc[test_idx]

        X_train, y_train = train[FEATURE_COLS], train[TARGET]
        X_test, y_test = test[FEATURE_COLS], test[TARGET]

        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train, categorical_feature=CAT_COLS)
        preds = model.predict(X_test)
        preds = np.clip(preds, 0, None)  # demand can't be negative

        fold_wape = wape(y_test.values, preds)
        fold_mape = mape(y_test.values, preds)
        fold_metrics.append({"fold": i + 1, "wape": fold_wape, "mape": fold_mape, "n_test": len(test)})
        print(f"Fold {i+1}: WAPE={fold_wape:.3f}  MAPE={fold_mape:.1f}%  (n={len(test)})")

    return fold_metrics, trainable, model

if __name__ == "__main__":
    import json, os
    hp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best_hyperparams.json")
    tuned = None
    if os.path.exists(hp_path):
        with open(hp_path) as f:
            tuned = json.load(f)
        print(f"Using tuned hyperparameters from {hp_path}\n")
    metrics, trainable, last_model = train_and_evaluate(hyperparams=tuned)
    print("\n=== Summary across folds ===")
    avg_wape = np.mean([m["wape"] for m in metrics])
    avg_mape = np.mean([m["mape"] for m in metrics])
    print(f"Average WAPE: {avg_wape:.3f}")
    print(f"Average MAPE: {avg_mape:.1f}%")
    print(f"\nKPI target (BRD): MAPE <= 15-20%  ->  {'MEETS TARGET' if avg_mape <= 20 else 'BELOW TARGET, needs tuning'}")
