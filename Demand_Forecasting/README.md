# Quick-Commerce Demand Forecasting Model — FINAL

This is the canonical, locked-in model for the capstone project
("Logistics Warehouse SKU Dispatch Planning Based on Demand").

## The model

| File | Purpose |
|---|---|
| `qc_final_model.pkl` | The trained LightGBM model (Tweedie objective). **This is the one.** |
| `qc_model_metadata.json` | Feature list, training details, validated metrics. |
| `qc_predict_final.py` | Run this to get forecasts. Supports whole-catalog, selective, or single-SKU queries; day-wise AND total-units output; input validation. |

## Validated performance (what goes in the BRD / defense)

- **WAPE = 0.180, MAPE = 18.4%** — measured via proper 3-fold rolling-origin
  time-series cross-validation (the methodology used throughout this
  project; never a single lucky holdout).
- Meets the BRD KPI target (MAPE ≤ 15–20%) **directly at daily SKU x
  warehouse granularity** — no weekly aggregation needed, unlike the earlier
  M5-dataset attempt.
- Naive baselines for comparison: lag-7 WAPE=0.322/MAPE=32.4%,
  trailing-28-day-average WAPE=0.295/MAPE=30.2%. The model beats both by a
  wide margin.

## Training data

- `quick_commerce_with_events_clean.csv` — 328,122 rows after cleaning,
  300 products x 6 warehouses x 6 cities, 2023-01-29 to 2025-12-31.
- 605 stockout-day rows excluded from training (real censoring, using the
  `stock_on_hand` column — something the earlier M5 dataset could not do).
- Includes a real Indian holiday/festival calendar (`event_name_1` /
  `event_type_1`).

## How to run a forecast

```
python3 qc_predict_final.py --days 7
python3 qc_predict_final.py --days 7 --products 10 --warehouses WH03
python3 qc_predict_final.py --days 14 --products 10,25,50
```

Produces:
- `qc_forecast_daywise.csv` — day-by-day prediction
- `qc_forecast_totals.csv` — total predicted units per SKU x warehouse,
  summed across the requested window, plus a console-printed grand total

## Keeping it dynamic (optional, supporting infrastructure)

- `qc_retrain.py` — safe retrain pipeline. Retrains on current data,
  compares new vs. old model on the same recent holdout, and only
  replaces the live model if the new one is not worse. Always backs up
  the previous model first.
- `qc_drift_monitor.py` — checks the live model's recent accuracy against
  its validated baseline, at both the pooled (catalog-wide) and per-SKU
  level, and flags when a retrain is warranted.

These exist to demonstrate the model isn't static, but **the model files
above are the ones actually in use** — nothing here auto-retrains or
auto-promotes on its own; both scripts only act when you run them.

## Not part of the final deliverable

- `retrain_pipeline_test/` — leftover artifacts from testing
  `qc_retrain.py`'s promote logic. Not a different/better model; same
  data, just evaluated on a different (single 30-day) window as part of
  proving the retrain pipeline works. Safe to ignore or delete.
- `qc_predict.py`, `qc_predict_v2.py`, `qc_predict_v3.py` — earlier
  working versions, kept only for history. Use `qc_predict_final.py`.
