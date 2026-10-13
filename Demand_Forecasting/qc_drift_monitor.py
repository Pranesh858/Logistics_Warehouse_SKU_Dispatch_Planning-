"""
Drift monitor: tracks the live model's accuracy over time and flags when
it has degraded enough to justify a retrain, instead of retraining on a
blind fixed schedule (which could retrain too often -- wasteful -- or too
rarely -- stale).

Usage:
    python3 qc_drift_monitor.py --window-days 7 --threshold 1.25

This compares the model's WAPE on the most recent `window_days` of actual
data against its own validated baseline WAPE (from qc_model_metadata.json).
If recent WAPE exceeds baseline * threshold, it flags DRIFT_DETECTED.
"""
import argparse
import json
import joblib
import numpy as np
import pandas as pd

from qc_features import build_feature_frame
from qc_train_model import prepare_dataset, wape, mape, FEATURE_COLS, TARGET

MODEL_PATH = "qc_final_model.pkl"
METADATA_PATH = "qc_model_metadata.json"


def check_drift(window_days=7, threshold=1.25, data_path=None, per_sku_threshold=2.0, min_rows_per_sku=5):
    """
    Checks drift at TWO levels, because a pooled-only check is blind to a
    single important SKU going bad (it gets averaged away -- confirmed
    empirically: a SKU that is 0.3% of total rows barely moves the pooled
    WAPE even when its own demand crashed 80%):

      1. Pooled WAPE across all SKUs -- catches a system-wide shift.
      2. Per-SKU WAPE -- catches an individual SKU crashing/spiking even
         when the rest of the catalog is fine.
    """
    with open(METADATA_PATH) as f:
        meta = json.load(f)
    baseline_wape = meta["cv_metrics"]["avg_wape"]

    model = joblib.load(MODEL_PATH)
    df = build_feature_frame(data_path) if data_path else build_feature_frame()
    trainable = prepare_dataset(df)

    max_date = trainable["date"].max()
    recent = trainable[trainable["date"] >= max_date - pd.Timedelta(days=window_days)].copy()
    if recent.empty:
        print("Not enough recent data to check drift.")
        return False

    recent["pred"] = np.clip(model.predict(recent[FEATURE_COLS]), 0, None)

    # --- 1. Pooled check ---
    pooled_wape = wape(recent[TARGET].values, recent["pred"].values)
    pooled_mape = mape(recent[TARGET].values, recent["pred"].values)
    pooled_ratio = pooled_wape / baseline_wape
    pooled_drifted = pooled_ratio > threshold

    print("=== Pooled (catalog-wide) drift check ===")
    print(f"Baseline WAPE: {baseline_wape:.3f}  |  Recent {window_days}-day WAPE: {pooled_wape:.3f}  "
          f"(MAPE {pooled_mape:.1f}%, n={len(recent):,})  |  ratio: {pooled_ratio:.2f}x")
    print("DRIFT_DETECTED (catalog-wide)" if pooled_drifted else "No catalog-wide drift.")

    # --- 2. Per-SKU check ---
    print(f"\n=== Per-SKU drift check (flags any SKU >={per_sku_threshold}x its own normal error) ===")
    drifted_skus = []
    for (pid, wh), g in recent.groupby(["product_id", "warehouse_id"]):
        if len(g) < min_rows_per_sku:
            continue
        sku_wape = wape(g[TARGET].values, g["pred"].values)
        if sku_wape / max(baseline_wape, 1e-6) > per_sku_threshold:
            drifted_skus.append({"product_id": pid, "warehouse_id": wh, "wape": round(sku_wape, 3),
                                  "avg_actual": round(g[TARGET].mean(), 1), "avg_predicted": round(g["pred"].mean(), 1)})

    if drifted_skus:
        print(f"{len(drifted_skus)} SKU(s) flagged for individual drift:")
        for d in sorted(drifted_skus, key=lambda x: -x["wape"]):
            print(f"  product_id={d['product_id']} warehouse={d['warehouse_id']}: "
                  f"WAPE={d['wape']}, avg actual={d['avg_actual']}, avg predicted={d['avg_predicted']}")
    else:
        print("No individual SKUs flagged.")

    drifted = pooled_drifted or len(drifted_skus) > 0
    print()
    if drifted:
        print("OVERALL: DRIFT_DETECTED -- recommend running qc_retrain.py --promote, "
              "or investigating the flagged SKU(s) specifically before a full retrain.")
    else:
        print("OVERALL: No significant drift at either level.")

    return drifted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--threshold", type=float, default=1.25,
                         help="Flag drift when recent WAPE exceeds baseline WAPE * threshold")
    parser.add_argument("--data", type=str, default=None)
    args = parser.parse_args()
    check_drift(args.window_days, args.threshold, args.data)
