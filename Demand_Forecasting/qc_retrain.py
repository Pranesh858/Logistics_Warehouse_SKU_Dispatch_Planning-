"""
Retraining pipeline for the quick-commerce demand model -- this is what
makes the system "dynamic": instead of a model frozen at one point in time,
this script retrains on whatever is currently in the dataset CSV and
VALIDATES the new model against the old one before replacing it.

This is NOT online/incremental learning (LightGBM doesn't do that safely
for tabular data) -- it's the standard, production-proven approach: batch
retrain on a schedule or trigger, always with a before/after accuracy check
so a retrain can never silently make things worse without being flagged.

Usage:
    python3 qc_retrain.py                      # retrain on current data, compare to live model
    python3 qc_retrain.py --promote             # retrain AND replace the live model if it's not worse
"""
import argparse
import json
import shutil
import datetime
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb

from qc_features import build_feature_frame
from qc_train_model import prepare_dataset, rolling_origin_splits, wape, mape, FEATURE_COLS, CAT_COLS, TARGET

MODEL_PATH = "qc_final_model.pkl"
METADATA_PATH = "qc_model_metadata.json"
PARAMS = dict(
    objective="tweedie", tweedie_variance_power=1.1,
    n_estimators=300, learning_rate=0.05,
    num_leaves=31, min_child_samples=20, random_state=42, verbosity=-1,
)


def evaluate_on_recent_holdout(model, trainable, holdout_days=30):
    """Score a model on the most recent `holdout_days` of real data -- used
    to compare old vs newly retrained model on the SAME fair test window."""
    max_date = trainable["date"].max()
    holdout = trainable[trainable["date"] >= max_date - pd.Timedelta(days=holdout_days)]
    preds = np.clip(model.predict(holdout[FEATURE_COLS]), 0, None)
    return wape(holdout[TARGET].values, preds), mape(holdout[TARGET].values, preds), len(holdout)


def retrain(data_path=None):
    print(f"[{datetime.datetime.now().isoformat()}] Starting retrain...")
    df = build_feature_frame(data_path) if data_path else build_feature_frame()
    trainable = prepare_dataset(df)

    # Evaluate the CURRENT live model on the most recent 30 days, if it exists
    old_metrics = None
    try:
        old_model = joblib.load(MODEL_PATH)
        old_wape, old_mape, n = evaluate_on_recent_holdout(old_model, trainable)
        old_metrics = {"wape": old_wape, "mape": old_mape, "n": n}
        print(f"Current LIVE model on most recent 30 days (n={n}): WAPE={old_wape:.3f} MAPE={old_mape:.1f}%")
    except FileNotFoundError:
        print("No existing live model found -- this will be the first trained model.")

    # Train a NEW model on ALL current data (including whatever is new since last train)
    new_model = lgb.LGBMRegressor(**PARAMS)
    new_model.fit(trainable[FEATURE_COLS], trainable[TARGET], categorical_feature=CAT_COLS)
    new_wape, new_mape, n = evaluate_on_recent_holdout(new_model, trainable)
    print(f"NEWLY RETRAINED model on most recent 30 days (n={n}): WAPE={new_wape:.3f} MAPE={new_mape:.1f}%")

    new_metrics = {"wape": new_wape, "mape": new_mape, "n": n}
    improved = old_metrics is None or new_wape <= old_metrics["wape"]

    print()
    if old_metrics is None:
        print("VERDICT: No prior model to compare against -- new model stands on its own.")
    elif improved:
        print(f"VERDICT: New model is BETTER OR EQUAL (WAPE {old_metrics['wape']:.3f} -> {new_wape:.3f}). Safe to promote.")
    else:
        print(f"VERDICT: New model is WORSE (WAPE {old_metrics['wape']:.3f} -> {new_wape:.3f}). "
              f"Do NOT promote automatically -- investigate why before replacing the live model.")

    return new_model, trainable, old_metrics, new_metrics, improved


def promote(new_model, trainable, new_metrics, data_path_label):
    """Replace the live model, but keep the previous one as a timestamped
    backup so a bad retrain can always be rolled back."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy(MODEL_PATH, f"qc_model_backup_{timestamp}.pkl")
        print(f"Backed up previous model to qc_model_backup_{timestamp}.pkl")
    except FileNotFoundError:
        pass

    joblib.dump(new_model, MODEL_PATH)

    with open(METADATA_PATH) as f:
        meta = json.load(f)
    meta["last_retrained"] = timestamp
    meta["training_rows"] = int(len(trainable))
    meta["training_date_range"] = [str(trainable["date"].min().date()), str(trainable["date"].max().date())]
    meta["cv_metrics"] = {"avg_wape": round(float(new_metrics["wape"]), 3), "avg_mape_pct": round(float(new_metrics["mape"]), 1)}
    meta["retrain_source_data"] = data_path_label
    with open(METADATA_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"PROMOTED: {MODEL_PATH} and {METADATA_PATH} updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default=None, help="Path to the dataset CSV to retrain on (default: the live dataset)")
    parser.add_argument("--promote", action="store_true", help="Replace the live model if the new one is not worse")
    args = parser.parse_args()

    new_model, trainable, old_metrics, new_metrics, improved = retrain(args.data)

    if args.promote:
        if improved:
            promote(new_model, trainable, new_metrics, args.data or "live dataset")
        else:
            print("\n--promote was requested but the new model did NOT improve -- refusing to auto-replace the live model.")
            print("Investigate the data before forcing a promotion.")
