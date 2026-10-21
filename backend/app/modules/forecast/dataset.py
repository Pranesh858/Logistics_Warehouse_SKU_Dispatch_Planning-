"""Dataset upload and retraining. One upload is staged, previewed, then applied in a background thread."""
import io
import threading
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.ml import train
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


def stage(filename: str, content: bytes) -> dict:
    """Validate an upload and keep it ready to apply. Nothing about the live model changes here."""
    if status()["state"] == "running":
        raise BadRequestError("A retrain is already running. Wait for it to finish.")
    clean, errors, warnings = train.validate_upload(_read(filename, content))
    old_raw = pd.read_csv(settings.dataset_path, parse_dates=["date"])
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
    _set(state="ready", preview={**preview, **summary}, result=None, error=None, step="", progress=0)
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
        if _state["state"] not in ("ready", "rejected"):
            raise BadRequestError("Upload and check a dataset first.")
        _state.update(state="running", step="Reading the uploaded file", progress=5, result=None, error=None)
    threading.Thread(target=_run, args=(force, on_done), daemon=True).start()
    return status()


def _run(force: bool, on_done):
    try:
        new = pd.read_csv(_staged_path(), parse_dates=["date"])
        old_raw = pd.read_csv(settings.dataset_path, parse_dates=["date"])
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
        _staged_path().unlink(missing_ok=True)
        _set(state="done", step="Done", progress=100, result=result)
    except Exception as exc:  # shown to the admin; the live model was not replaced unless promote finished
        _set(state="failed", step="Failed", progress=100, error=str(exc))
        return
    try:
        on_done(result)   # warm the forecast and rebuild the dispatch plan; the new model is already live
    except Exception:
        pass
