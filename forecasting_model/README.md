# SKU Demand Forecasting Model

Global LightGBM model trained across all 300 SKUs in the synthetic dataset
(`quick_commerce_sku_demand_2023_2025.csv`), producing p10/p50/p90 quantile
forecasts (median + 80% confidence interval) per SKU.

## Validated Performance
- **MAPE: 17.8%** (rolling-origin cross-validation, 3 folds)
- **WAPE: 0.180**
- **80% interval coverage: 77.7%** (target ~80% — well-calibrated)
- Meets BRD KPI target: MAPE <= 15-20%

## Upgrades Implemented (Status: All 3 Complete)
| Upgrade | Status | Measured Effect |
|---|---|---|
| Recursive multi-step forecasting | ✅ Implemented (`recursive_predict.py`) | Fixes flat repeated-value forecasts — now shows a real day-to-day trajectory |
| Holiday/festival calendar features | ✅ Implemented (`is_holiday`, `days_to_next_holiday`, etc. in `features.py`) | Neutral on this synthetic dataset (MAPE 17.7% -> 17.8%) — see note below |
| Hyperparameter tuning (Optuna) | ✅ Implemented (`tune_hyperparams.py`) | No reliable improvement found with the trial budget used (19.2% -> 19.4% MAPE on full CV) — default hyperparameters kept for the shipped model |

**Honest note on holiday features and tuning**: both were correctly implemented
and verified to run, but did not measurably improve accuracy *on this specific
synthetic dataset*. This is because the synthetic data's promotional/seasonal
spikes were generated independently of real calendar holidays, so the holiday
features have nothing to correlate with here. On real production data, where
holidays genuinely drive demand, these features are expected to help — the
capability is built and ready, just not proven on synthetic data by
construction. Hyperparameter tuning used a reduced search (8 trials, 2 CV
folds) due to compute time constraints; a larger search (50+ trials) is a
reasonable next step if further accuracy gains are needed later.

## Files
| File | Purpose |
|---|---|
| `features.py` | Feature engineering: lags, rolling stats, calendar features, holiday/festival calendar, stockout censoring |
| `train_model.py` | Core training + rolling-origin CV evaluation (accepts optional tuned hyperparameters) |
| `train_final_model.py` | Trains the final production model on 100% of data, saves artifacts |
| `tune_hyperparams.py` | Optuna hyperparameter search using rolling-origin CV as the objective |
| `quantile_and_explain.py` | Quantile regression (p10/p50/p90) + SHAP explainability + cold-start fallback logic |
| `predict.py` | Single-snapshot forecast (simpler, but repeats the same value each day) |
| `recursive_predict.py` | Recursive multi-day forecast for ONE SKU, updating lag/rolling/holiday features day-by-day |
| `batch_forecast.py` | **Use this for a real dispatch plan**: forecasts ALL SKUs (or a chosen subset) in one run, outputs a combined CSV. Add `--rollup` to also get a period-total summary per SKU in the same run. |
| `monthly_rollup.py` | Aggregates day-by-day forecasts into a single period total per SKU (e.g., monthly), with statistically proper (not naive-summed) confidence intervals. Can be run standalone, or automatically via `batch_forecast.py --rollup`. |
| `model_p10.pkl` / `model_p50.pkl` / `model_p90.pkl` | Trained model artifacts (LightGBM, via joblib) |
| `model_metadata.json` | Model version, training date, features used, validated metrics, full changelog notes |
| `best_hyperparams.json` | Best hyperparameters found by the tuning run (not currently used in the shipped model — see note above) |

## Usage
```bash
pip install lightgbm shap optuna joblib pandas numpy tqdm --break-system-packages

# Reproduce training + validation from scratch (uses tuned hyperparams if best_hyperparams.json exists)
python train_model.py

# Re-run hyperparameter tuning (optional, ~5-10 min)
python tune_hyperparams.py

# Train and save final production model
python train_final_model.py

# Forecast a specific SKU (recursive, one SKU at a time)
python recursive_predict.py --sku 4 --days 7

# Forecast ALL SKUs at once (what you need for a real dispatch plan)
python batch_forecast.py --days 7
# -> saves forecast_all_skus.csv with every SKU's day-by-day forecast

# Forecast ALL SKUs + get a period-total summary in one command (recommended for planning)
python batch_forecast.py --days 30 --rollup
# -> saves forecast_all_skus.csv (daily detail)
# -> saves forecast_totals.csv (one total per SKU for the whole 30-day period)

# Forecast just a subset of SKUs
python batch_forecast.py --days 7 --skus 1,4,12,50

# Custom output filenames
python batch_forecast.py --days 30 --rollup --out monthly_daily.csv --rollup-out monthly_summary.csv

# Roll up an EXISTING daily forecast file separately (if you didn't use --rollup)
python monthly_rollup.py --input forecast_all_skus.csv --out forecast_totals.csv

# Single-snapshot forecast (simpler, but repeats the same value each day)
python predict.py --sku 4 --days 7
```

## Design Notes
- **Global model, not per-SKU**: one LightGBM model learns across all SKUs, so
  patterns from well-stocked SKUs help forecast sparser ones (standard
  approach for large-catalog retail forecasting, per the M5 benchmark).
- **Stockout censoring**: days with `stock_on_hand == 0` are excluded from the
  training target, since true demand is undercounted (censored) on those days.
- **Explainability**: `quantile_and_explain.py` shows SHAP-based feature
  attribution per forecast (e.g., "roll_mean_7: -28 units") satisfying the
  BRD's Core Principle that every recommendation must be explainable.
- **Cold-start fallback**: SKUs with <28 days of history fall back to a
  trailing 4-week average rather than an unreliable model prediction.
- **Holiday calendar**: `HOLIDAYS` in `features.py` is an illustrative
  India-relevant calendar (2023-2026). Lunar-calendar festival dates (Holi,
  Diwali) are approximate and should be confirmed against an authoritative
  calendar before production use.
- **Recursive forecasting assumes no future promotions**: since future
  `promotion_flag`/`discount_pct` aren't known in advance, `recursive_predict.py`
  assumes no promotion for future days. This can be replaced with a planned-
  promotions calendar once available, which would likely improve accuracy
  further for promo-heavy periods.
- **Accuracy degrades the further out you forecast**: each day's prediction
  feeds into the next, so by day 20-30 the model is relying mostly on its own
  earlier predictions rather than real data. The model was validated on
  30-day windows; treat forecasts beyond ~30 days as untested.
- **Period rollup uncertainty is combined properly, not naively summed**:
  `monthly_rollup.py` does not simply add up each day's p10/p90 to get a
  monthly range (that would overstate uncertainty, since daily errors partly
  cancel out over a month rather than all missing in the same direction).
  Instead it converts each day's confidence band to a standard deviation,
  combines variances across days, and reconstructs a statistically proper
  p10/p50/p90 for the total period.
- **Batch runtime**: `batch_forecast.py` runs all 300 SKUs for a 7-day
  horizon in ~25 seconds on a typical laptop. Longer horizons (e.g., 30 days)
  take proportionally longer since each day is a separate recursive step.
