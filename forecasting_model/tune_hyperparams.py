"""
Hyperparameter tuning for the global LightGBM model using Optuna.
Objective = average WAPE across rolling-origin CV folds (same validation
method used for the reported accuracy numbers, so the tuned model is
evaluated honestly, not overfit to a single split).
"""
import os
import json
import numpy as np
import optuna
import lightgbm as lgb
from features import build_feature_frame
from train_model import FEATURE_COLS, CAT_COLS, TARGET, prepare_dataset, rolling_origin_splits, wape

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
optuna.logging.set_verbosity(optuna.logging.WARNING)


def make_objective(trainable, splits):
    def objective(trial):
        params = {
            "objective": "regression",
            "n_estimators": trial.suggest_int("n_estimators", 150, 500),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 15, 63),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 5.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 5.0, log=True),
            "random_state": 42,
            "verbosity": -1,
        }

        fold_wapes = []
        for train_idx, test_idx in splits:
            train, test = trainable.loc[train_idx], trainable.loc[test_idx]
            model = lgb.LGBMRegressor(**params)
            model.fit(train[FEATURE_COLS], train[TARGET], categorical_feature=CAT_COLS)
            preds = np.clip(model.predict(test[FEATURE_COLS]), 0, None)
            fold_wapes.append(wape(test[TARGET].values, preds))
        return float(np.mean(fold_wapes))
    return objective


def main(n_trials=30, n_folds=3):
    print("Building features (with holiday calendar)...")
    df = build_feature_frame()
    trainable = prepare_dataset(df)
    splits = rolling_origin_splits(trainable, n_folds=n_folds, test_days=30)
    print(f"Tuning on {len(trainable)} rows, {len(splits)} CV folds, {n_trials} trials...")

    study = optuna.create_study(direction="minimize")
    study.optimize(make_objective(trainable, splits), n_trials=n_trials, show_progress_bar=False)

    print("\nBest WAPE:", round(study.best_value, 4))
    print("Best params:")
    for k, v in study.best_params.items():
        print(f"  {k}: {v}")

    with open(os.path.join(MODEL_DIR, "best_hyperparams.json"), "w") as f:
        json.dump(study.best_params, f, indent=2)
    print("\nSaved best_hyperparams.json")
    return study.best_params


if __name__ == "__main__":
    main(n_trials=8, n_folds=2)
