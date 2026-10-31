"""Dataset upload and retraining. One upload is staged, previewed, then applied in a background thread."""
import io
import threading
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.ml import backtest, train
from app.ml.features import read_history, using_sample_dataset
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def _staged_path() -> Path:
    p = Path(settings.dataset_path).parent / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p / "staged.csv"


def status() -> dict:
    with _lock:
        return dict(_state)


def _set(**kw):
    with _lock:
        _state.update(kw)


def _read(filename: str, content: bytes) -> pd.DataFrame:
    try:
        if filename.lower().endswith((".xlsx", ".xlsm")):
            return pd.read_excel(io.BytesIO(content))
        return pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # unreadable file
        raise BadRequestError("The file could not be read. Upload a CSV or Excel (.xlsx) file.") from exc


def last_trained() -> str | None:
    import json
    from pathlib import Path
    try:
        meta = json.loads(Path(settings.model_metadata_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return meta.get("retrained_at") or (meta.get("training_date_range") or [None, None])[1]


def _baseline_wape() -> float | None:
    """How accurate the model in use was when it was accepted, so a new one can be judged against it."""
    import json
    from pathlib import Path
    try:
        meta = json.loads(Path(settings.model_metadata_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    check = meta.get("retrain_check") or {}
    return check.get("wape_after") or (meta.get("cv_metrics") or {}).get("avg_wape")


def _retrain_on_history(force: bool = False) -> dict:
    """Retrain on the sales history as it now stands. Used by the schedule and by the Retrain now button;
    no upload is involved, so this is for history that grew through the ERP sales feed.

    `force` promotes the new model even if it scores worse than the one in use. On a fresh clone the history is
    the 120-day sample and the model in use was trained on three years, so a retrain there is always worse and
    only goes through when the admin chooses it."""
    import pandas as pd

    on_sample = using_sample_dataset()
    raw = read_history()
    _set(step="Testing a new model on the most recent weeks", progress=30)
    cutoff = raw["date"].max() - pd.Timedelta(days=train.HOLDOUT_DAYS)
    new = train.holdout_metrics(raw, cutoff)
    wape_new, rows = new["wape"], new["rows"]
    baseline = _baseline_wape()
    worse = bool(baseline and wape_new == wape_new and wape_new > baseline * (1 + train.MAX_WAPE_WORSENING))
    comparison = {"holdout_days": train.HOLDOUT_DAYS, "rows_scored": rows,
                  "wape_before": round(baseline, 4) if baseline else None, "wape_after": round(wape_new, 4),
                  "mape_after_pct": round(new["mape_pct"], 1), "worse": worse,
                  "change_pct": round((wape_new - baseline) / baseline * 100, 1) if baseline else 0.0,
                  "history_is_sample": on_sample}
    if worse and not force:
        return {"promoted": False, "comparison": comparison, "left_out": 0}
    _set(step="Training the final model on all data", progress=70)
    frame = train.features_from_raw(raw)
    model = train.fit(frame)
    _set(step="Saving and switching to the new model", progress=90)
    backup = train.promote(model, raw, frame, comparison)
    runtime.reload()
    meta = runtime.meta
    result = {"promoted": True, "comparison": comparison, "backup": backup, "left_out": 0,
              "products": meta["products"], "warehouses": meta["warehouses"],
              "history_to": meta["training_date_range"][1], "training_rows": meta["training_rows"],
              "new_product_ids": []}
    _rescore(raw, result)
    return result


def _rescore(raw, result: dict) -> None:
    """Re-measure the new model so the accuracy page stops describing the old one.

    The model is already live at this point: the figures are a description of it, not a gate on it, so a
    failure here is recorded on the result and does not undo the retrain.
    """
    if not settings.refresh_accuracy_after_retrain:
        return
    try:
        _set(step="Re-scoring the forecast for the accuracy page", progress=95)
        kpis = backtest.refresh(raw)
        result["accuracy"] = kpis
    except Exception as exc:  # noqa: BLE001
        result["accuracy_error"] = str(exc)
        print(f"[accuracy] could not re-score after the retrain: {exc}", flush=True)


def start_retrain(on_done, reason: str = "manual", force: bool = False) -> dict:
    """Retrain on the current history, in the background. Same status endpoint as an upload; `kind` tells the
    two apart, so "use it anyway" after a rejection repeats the right one."""
    with _lock:
        if _state["state"] == "running":
            raise BadRequestError("A retrain is already running.")
        _state.update(state="running", step="Reading the sales history", progress=5, result=None, error=None,
                      reason=reason, kind="history")
    threading.Thread(target=_run_history, args=(on_done, force), daemon=True).start()
    return status()


def _run_history(on_done, force: bool = False):
    try:
        result = _retrain_on_history(force)
    except Exception as exc:
        _set(state="failed", step="Failed", progress=100, error=str(exc))
        return
    if not result["promoted"]:
        _set(state="rejected", step="Kept the current model", progress=100, result=result)
        return
    _set(state="done", step="Done", progress=100, result=result)
    try:
        on_done(result)
    except Exception:
        pass


def stage(filename: str, content: bytes) -> dict:
    """Validate an upload and keep it ready to apply. Nothing about the live model changes here."""
    if status()["state"] == "running":
        raise BadRequestError("A retrain is already running. Wait for it to finish.")
    clean, errors, warnings = train.validate_upload(_read(filename, content))
    old_raw = read_history()
    preview = {"filename": filename, "errors": errors, "warnings": warnings}
    if errors:
        _set(state="idle", preview=preview, result=None, error=None)
        return status()
    summary = train.summarize_upload(clean, old_raw)
    if summary["short_history_pairs"]:
        warnings.append(
            f"{len(summary['short_history_pairs'])} new SKU/warehouse combination(s) have fewer than "
            f"{train.MIN_DAYS_PER_SKU} days of history and will be left out until more data is uploaded.")
    clean.assign(date=clean["date"].dt.strftime("%Y-%m-%d")).to_csv(_staged_path(), index=False)
    _set(state="ready", preview={**preview, **summary}, result=None, error=None, step="", progress=0,
         kind="upload", reason="manual")
    return status()


def discard() -> dict:
    if status()["state"] == "running":
        raise BadRequestError("A retrain is running and cannot be cancelled.")
    _staged_path().unlink(missing_ok=True)
    _set(state="idle", preview=None, result=None, error=None)
    return status()


def start(force: bool, on_done) -> dict:
    """Begin the retrain in a background thread. `on_done(result)` runs in that thread when it ends."""
    with _lock:
        if _state["state"] == "running":
            raise BadRequestError("A retrain is already running.")
        if _state["state"] not in ("ready", "rejected") or _state.get("kind") != "upload":
            raise BadRequestError("Upload and check a dataset first.")
        _state.update(state="running", step="Reading the uploaded file", progress=5, result=None, error=None)
    threading.Thread(target=_run, args=(force, on_done), daemon=True).start()
    return status()


def _run(force: bool, on_done):
    try:
        new = pd.read_csv(_staged_path(), parse_dates=["date"])
        old_raw = read_history()
        _set(step="Joining with the existing history", progress=15)
        merged, dropped = train.merge_history(old_raw, new)
        _set(step="Testing the new model against the current one on recent days", progress=30)
        comparison = train.compare_models(old_raw, merged)
        if comparison["worse"] and not force:
            _set(state="rejected", step="Kept the current model", progress=100,
                 result={"promoted": False, "comparison": comparison, "left_out": len(dropped)})
            return
        _set(step="Training the final model on all data", progress=70)
        frame = train.features_from_raw(merged)
        model = train.fit(frame)
        _set(step="Saving and switching to the new model", progress=90)
        backup = train.promote(model, merged, frame, comparison)
        runtime.reload()
        meta = runtime.meta
        result = {
            "promoted": True, "comparison": comparison, "backup": backup, "left_out": len(dropped),
            "products": meta["products"], "warehouses": meta["warehouses"],
            "history_to": meta["training_date_range"][1], "training_rows": meta["training_rows"],
            "new_product_ids": _state["preview"].get("new_product_ids", []),
        }
        _rescore(merged, result)
        _staged_path().unlink(missing_ok=True)
        _set(state="done", step="Done", progress=100, result=result)
    except Exception as exc:  # shown to the admin; the live model was not replaced unless promote finished
        _set(state="failed", step="Failed", progress=100, error=str(exc))
        return
    try:
        on_done(result)   # warm the forecast and rebuild the dispatch plan; the new model is already live
    except Exception:
        pass
