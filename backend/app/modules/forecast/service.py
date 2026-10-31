import json

import pandas as pd

from app.ml.explain import add_ranges, explain, load_intervals, total_range
from app.ml.predict import InputValidationError, forecast_next_days, summarize_totals
from app.modules.forecast.runtime import runtime
from app.shared.exceptions import BadRequestError


def list_skus() -> list[dict]:
    snap = runtime.stock_snapshot().merge(runtime.sku_info()[["product_id", "category"]], on="product_id", how="left")
    return json.loads(snap.sort_values(["product_id", "warehouse_id"]).to_json(orient="records"))


def run_forecast(days: int, product_ids: list[int] | None, warehouse_ids: list[str] | None) -> dict:
    try:
        daywise = forecast_next_days(
            runtime.model, runtime.meta, days=days, product_ids=product_ids,
            warehouse_ids=warehouse_ids, frame=runtime.frame,
        )
    except InputValidationError as exc:
        raise BadRequestError(str(exc)) from exc
    totals, _, grand_total = summarize_totals(daywise, days)
    iv = load_intervals()
    daywise = add_ranges(daywise, iv)
    ranges = [total_range(t, days, iv) for t in totals["total_predicted_units"]]
    totals["total_low"] = [r[0] for r in ranges]
    totals["total_high"] = [r[1] for r in ranges]
    daywise["date"] = daywise["date"].dt.strftime("%Y-%m-%d")
    meta = runtime.meta
    return {
        "days": days,
        "grand_total": grand_total,
        "totals": json.loads(totals.to_json(orient="records")),
        "daywise": json.loads(daywise.to_json(orient="records")),
        "model": {
            "objective": meta["objective"],
            "training_rows": meta["training_rows"],
            "wape": meta["cv_metrics"]["avg_wape"],
            "mape_pct": meta["cv_metrics"]["avg_mape_pct"],
        },
    }


def explain_forecast(product_id: int, warehouse_id: str, days: int) -> dict:
    try:
        return explain(runtime.model, runtime.meta, product_id, warehouse_id, days, full=runtime.frame)
    except InputValidationError as exc:
        raise BadRequestError(str(exc)) from exc


def demand_totals(days: int, product_ids: list[int] | None = None) -> pd.DataFrame:
    """SKU x warehouse totals, used by the dispatch outlook."""
    daywise = forecast_next_days(runtime.model, runtime.meta, days=days, product_ids=product_ids, frame=runtime.frame)
    totals, _, _ = summarize_totals(daywise, days)
    return totals


def accuracy_report(warehouse_id: str | None = None) -> dict:
    """Predicted vs actual demand from the leak-free backtest (model retrained up to each cut-off date, then forecast
    compared with what was really sold). It is computed offline and shipped as a file; see qc_backtest_export.py."""
    import json
    from pathlib import Path

    from app.core.config import settings

    path = Path(settings.backtest_path)
    if not path.exists():
        raise FileNotFoundError(path)
    report = json.loads(path.read_text(encoding="utf-8"))
    names = runtime.sku_info().set_index("product_id")["product_name"].to_dict()
    for r in report["by_sku"]:
        r["product_name"] = names.get(r["product_id"], f"SKU {r['product_id']}")
    return report if not warehouse_id else _accuracy_for_warehouse(report, warehouse_id)


def _accuracy_for_warehouse(report: dict, wh: str) -> dict:
    """The same report cut down to one warehouse (what a planner is allowed to see). Error by forecast day is a
    property of the shared model, so it stays as it is."""
    row = next((r for r in report["by_warehouse"] if r["warehouse_id"] == wh), None)
    if row is None:
        raise BadRequestError(f"No accuracy data for {wh}")
    skus = [r for r in report["by_sku"] if r["warehouse_id"] == wh]
    errs = [r["mean_abs_err_pct"] for r in skus if r["mean_abs_err_pct"] is not None]
    actual = sum(r["actual_7d"] for r in skus)
    kpis = {
        "day_wape": row["wape"], "day_mape_pct": row["mape_pct"], "day_bias_pct": row["bias_pct"],
        "sku_week_wape": round(sum(abs(r["forecast_7d"] - r["actual_7d"]) for r in skus) / actual, 3) if actual else 0.0,
        "sku_week_mape_pct": round(sum(errs) / len(errs), 1) if errs else 0.0,
        "total_predicted": row["predicted"], "total_actual": row["actual"], "sku_day_rows": 0, "skus": len(skus),
    }
    daily = report["daily_by_warehouse"].get(wh, [])
    return {**report, "kpis": kpis, "daily": daily, "daily_by_warehouse": {wh: daily},
            "by_warehouse": [row], "by_sku": skus, "warehouse_id": wh}
