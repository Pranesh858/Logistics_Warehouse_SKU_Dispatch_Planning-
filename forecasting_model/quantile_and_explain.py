"""
Adds to the core model:
1. Quantile regression (10th/50th/90th percentile) for prediction intervals
2. SHAP explainability per forecast
3. Cold-start fallback (trailing 4-week average) for sparse SKUs
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
import shap
from features import build_feature_frame
from train_model import FEATURE_COLS, CAT_COLS, TARGET, prepare_dataset, wape, mape

QUANTILES = [0.1, 0.5, 0.9]

def train_quantile_models(train, feature_cols=FEATURE_COLS, cat_cols=CAT_COLS, target=TARGET):
    """Train one model per quantile. Returns dict {quantile: model}."""
    models = {}
    X_train, y_train = train[feature_cols], train[target]
    for q in QUANTILES:
        m = lgb.LGBMRegressor(
            objective="quantile", alpha=q,
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            min_child_samples=20, random_state=42, verbosity=-1,
        )
        m.fit(X_train, y_train, categorical_feature=cat_cols)
        models[q] = m
    return models

def predict_with_intervals(models, X):
    preds = {}
    for q, m in models.items():
        preds[q] = np.clip(m.predict(X), 0, None)
    # enforce monotonicity: p10 <= p50 <= p90 (quantile crossing can happen with separate models)
    lo, mid, hi = preds[0.1], preds[0.5], preds[0.9]
    lo = np.minimum(lo, mid)
    hi = np.maximum(hi, mid)
    return pd.DataFrame({"forecast_p10": lo, "forecast_p50": mid, "forecast_p90": hi})

def cold_start_fallback(df, sku_history_threshold=28):
    """Flag SKUs with insufficient history for reliable model-based forecasting.
    These fall back to trailing 4-week average."""
    history_counts = df.groupby("product_id")["units_sold"].apply(lambda s: s.notna().sum())
    sparse_skus = history_counts[history_counts < sku_history_threshold].index.tolist()
    return sparse_skus

def fallback_forecast(df, sku_id, as_of_date, window_days=28):
    hist = df[(df["product_id"] == sku_id) & (df["date"] < as_of_date) & (df["date"] >= as_of_date - pd.Timedelta(days=window_days))]
    return hist["units_sold"].mean()

def explain_forecast(model_p50, X_row, feature_cols=FEATURE_COLS):
    """Return top SHAP feature contributions for a single forecast row."""
    explainer = shap.TreeExplainer(model_p50)
    shap_values = explainer.shap_values(X_row)
    contributions = pd.Series(shap_values[0], index=feature_cols).sort_values(key=abs, ascending=False)
    return contributions

if __name__ == "__main__":
    print("Building features...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)

    # Use last 30 days as holdout, everything before as train (final model, not CV loop)
    cutoff = trainable["date"].max() - pd.Timedelta(days=30)
    train = trainable[trainable["date"] < cutoff]
    test = trainable[trainable["date"] >= cutoff]
    print(f"Train: {len(train)} rows | Test: {len(test)} rows")

    print("\nTraining quantile models (p10, p50, p90)...")
    models = train_quantile_models(train)

    print("Generating predictions with intervals...")
    preds = predict_with_intervals(models, test[FEATURE_COLS])
    preds["actual"] = test[TARGET].values
    preds["product_id"] = test["product_id"].values
    preds["date"] = test["date"].values

    coverage = ((preds["actual"] >= preds["forecast_p10"]) & (preds["actual"] <= preds["forecast_p90"])).mean()
    print(f"\n80% interval empirical coverage: {coverage:.1%} (target ~80%)")

    p50_wape = wape(preds["actual"].values, preds["forecast_p50"].values)
    p50_mape = mape(preds["actual"].values, preds["forecast_p50"].values)
    print(f"Median (p50) forecast WAPE: {p50_wape:.3f}  MAPE: {p50_mape:.1f}%")

    # cold-start check
    sparse = cold_start_fallback(df)
    print(f"\nSKUs flagged for fallback (insufficient history): {len(sparse)} of {df['product_id'].nunique()}")

    # SHAP explainability demo on one real forecast
    print("\n=== Explainability demo: SHAP for one forecast ===")
    sample = test.iloc[[100]]
    sku_id = sample["product_id"].values[0]
    date = sample["date"].values[0]
    actual = sample[TARGET].values[0]
    pred_p50 = models[0.5].predict(sample[FEATURE_COLS])[0]
    print(f"SKU {sku_id} on {pd.Timestamp(date).date()}: forecast={pred_p50:.1f}, actual={actual:.1f}")
    contributions = explain_forecast(models[0.5], sample[FEATURE_COLS])
    print("Top 5 feature contributions (SHAP):")
    print(contributions.head(5))

    preds.to_csv("/home/claude/forecast/forecast_output_sample.csv", index=False)
    print("\nSaved forecast_output_sample.csv")
