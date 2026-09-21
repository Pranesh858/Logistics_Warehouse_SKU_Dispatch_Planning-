"""
Final production forecasting model.
Trains on the FULL trainable dataset (no holdout) and saves the model artifacts
(p10/p50/p90 LightGBM models) plus metadata for deployment/reuse.
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
import joblib
import json
from datetime import datetime
from features import build_feature_frame
from train_model import FEATURE_COLS, CAT_COLS, TARGET, prepare_dataset, wape, mape

QUANTILES = [0.1, 0.5, 0.9]
MODEL_VERSION = "sku-demand-lgbm-v1.0"

def train_final_models(train):
    models = {}
    X_train, y_train = train[FEATURE_COLS], train[TARGET]
    for q in QUANTILES:
        m = lgb.LGBMRegressor(
            objective="quantile", alpha=q,
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            min_child_samples=20, random_state=42, verbosity=-1,
        )
        m.fit(X_train, y_train, categorical_feature=CAT_COLS)
        models[q] = m
    return models

def main():
    print("Building feature frame from full dataset...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)
    print(f"Training on full trainable set: {len(trainable)} rows, {trainable['product_id'].nunique()} SKUs")

    print("\nTraining final p10 / p50 / p90 models...")
    models = train_final_models(trainable)

    # quick sanity check: in-sample fit quality (not a true holdout metric — see
    # train_model.py for the honest rolling-origin CV numbers: MAPE ~17.7-19.2%)
    preds_p50 = np.clip(models[0.5].predict(trainable[FEATURE_COLS]), 0, None)
    in_sample_mape = mape(trainable[TARGET].values, preds_p50)
    print(f"In-sample MAPE (sanity check only, not a validation metric): {in_sample_mape:.1f}%")

    # save model artifacts
    for q, m in models.items():
        joblib.dump(m, f"/home/claude/forecast/model_p{int(q*100)}.pkl")

    metadata = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now().isoformat(),
        "algorithm": "LightGBM (global model, all SKUs pooled)",
        "quantiles": QUANTILES,
        "feature_columns": FEATURE_COLS,
        "categorical_columns": CAT_COLS,
        "target": TARGET,
        "n_training_rows": int(len(trainable)),
        "n_skus": int(trainable["product_id"].nunique()),
        "validated_mape_pct": 17.8,
        "validated_wape": 0.180,
        "validation_method": "rolling-origin cross-validation (3 folds, 30-day test windows)",
        "kpi_target": "MAPE <= 15-20% (BRD Section 13)",
        "notes": "Stockout days excluded from training target (censored demand). "
                 "Cold-start SKUs (<28 days history) fall back to trailing 4-week average. "
                 "Recursive multi-step forecasting implemented (recursive_predict.py). "
                 "Holiday/festival calendar features included (is_holiday, days_to_next_holiday, "
                 "days_since_prev_holiday, is_near_holiday) -- measured neutral impact on this "
                 "synthetic dataset (MAPE 17.7% -> 17.8%) since the synthetic promo/seasonal "
                 "events were not generated to align with real calendar holidays; expected to "
                 "provide real benefit once trained on production data where actual holidays "
                 "genuinely drive demand. Hyperparameter tuning was run via Optuna "
                 "(tune_hyperparams.py, rolling-origin CV objective) but the limited search "
                 "(8 trials / 2 folds, due to compute time constraints) did not produce a "
                 "reliable improvement over default parameters on full 3-fold validation "
                 "(19.4% vs 19.2% MAPE on the point-prediction model) -- default hyperparameters "
                 "were kept for the shipped model. A larger tuning search (50+ trials) is a "
                 "reasonable next step if further gains are needed."
    }
    with open("/home/claude/forecast/model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print("\nSaved model artifacts:")
    print("  - model_p10.pkl, model_p50.pkl, model_p90.pkl")
    print("  - model_metadata.json")

if __name__ == "__main__":
    main()
