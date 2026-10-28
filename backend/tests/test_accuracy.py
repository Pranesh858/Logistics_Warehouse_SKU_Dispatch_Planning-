"""The accuracy report has to describe the model that is actually live.

It used to be a file produced once, offline: after a retrain the page kept showing the previous model's
figures, which looks right and is not. These tests cover the re-scoring, and that the report travels with
the model it belongs to.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.ml import backtest, train

API = "/api/v1"


def synthetic(days=150, skus=3) -> pd.DataFrame:
    """A small, well-behaved history: enough days for the 28-day lags, few enough SKUs to train in seconds."""
    rng = np.random.default_rng(7)
    start = pd.Timestamp("2025-01-01")
    rows = []
    for pid in range(1, skus + 1):
        wh = f"WH0{(pid % 2) + 1}"
        base = 40 + pid * 10
        for d in range(days):
            date = start + pd.Timedelta(days=d)
            units = base * (1 + 0.2 * np.sin(d / 7 * 2 * np.pi)) + rng.normal(0, 2)
            rows.append({
                "product_id": pid, "product_name": f"Item {pid}", "category": "Grocery", "date": date,
                "units_sold": round(max(units, 1.0), 1), "stock_on_hand": 5000.0, "price": 50.0 + pid,
                "discount_pct": 0, "promotion_flag": 0, "city": "Chennai", "warehouse_id": wh,
                "is_organic": False, "shelf_life_days": 120, "weight_g": 500,
                "event_name_1": "No Event", "event_type_1": "No Event",
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- the report itself
def test_the_report_has_every_section_the_accuracy_page_reads():
    report = backtest.run(synthetic(), horizon=5, count=2)
    for key in ("note", "horizon_days", "origins", "period", "target_mape_pct", "generated_at",
                "kpis", "daily", "daily_by_warehouse", "by_horizon", "by_warehouse", "by_sku"):
        assert key in report, f"the page reads {key}"
    for key in ("day_wape", "day_mape_pct", "day_bias_pct", "sku_week_wape", "sku_week_mape_pct",
                "total_predicted", "total_actual", "sku_day_rows", "skus"):
        assert key in report["kpis"], f"the page reads kpis.{key}"

    assert report["horizon_days"] == 5
    assert len(report["origins"]) == 2
    assert len(report["by_horizon"]) == 5
    assert [r["horizon_day"] for r in report["by_horizon"]] == [1, 2, 3, 4, 5]
    assert report["kpis"]["skus"] == 3
    assert len(report["by_sku"]) == 3


def test_the_windows_do_not_overlap_so_one_fortnight_cannot_carry_the_figure():
    report = backtest.run(synthetic(), horizon=5, count=2)
    dates = [r["date"] for r in report["daily"]]
    assert len(dates) == len(set(dates)) == 10          # 2 cut-offs x 5 days, each day scored once


def test_the_cut_offs_end_on_the_last_day_of_the_history():
    raw = synthetic()
    frame = train.features_from_raw(raw)
    cutoffs = backtest.origins(frame, horizon=5, count=2)
    assert cutoffs[-1] + pd.Timedelta(days=5) == raw["date"].max()
    assert cutoffs[0] < cutoffs[-1]


def test_a_history_too_short_to_score_says_so():
    with pytest.raises(ValueError):
        backtest.run(synthetic(days=30), horizon=5, count=2)


def test_the_figures_are_arithmetically_consistent():
    report = backtest.run(synthetic(), horizon=5, count=2)
    k = report["kpis"]
    assert k["sku_day_rows"] == len(report["daily"]) * k["skus"]        # every SKU scored on every day
    assert k["total_actual"] == pytest.approx(sum(d["actual"] for d in report["daily"]), rel=1e-3)
    assert k["total_predicted"] == pytest.approx(sum(d["predicted"] for d in report["daily"]), rel=1e-3)
    assert k["total_actual"] == pytest.approx(sum(w["actual"] for w in report["by_warehouse"]), rel=1e-3)
    bias = (k["total_predicted"] - k["total_actual"]) / k["total_actual"] * 100
    assert k["day_bias_pct"] == pytest.approx(bias, abs=0.1)
    assert 0 <= k["day_wape"] < 1


def test_the_report_is_written_whole_or_not_at_all(tmp_path):
    report = backtest.run(synthetic(), horizon=5, count=2)
    dest = tmp_path / "backtest.json"
    backtest.save(report, dest)
    assert json.loads(dest.read_text())["kpis"] == report["kpis"]
    assert not list(tmp_path.glob("*.tmp")), "the temporary file is moved into place, not left behind"


def test_refresh_replaces_the_file_the_accuracy_page_reads(tmp_path, monkeypatch):
    dest = tmp_path / "backtest.json"
    dest.write_text(json.dumps({"kpis": {"day_wape": 9.99}}))
    monkeypatch.setattr(settings, "backtest_path", str(dest))

    kpis = backtest.refresh(synthetic(), progress=None)
    assert kpis["day_wape"] != 9.99
    assert json.loads(dest.read_text())["kpis"]["day_wape"] == kpis["day_wape"]
    assert json.loads(dest.read_text())["generated_at"]


def test_progress_is_reported_for_every_cut_off():
    seen = []
    backtest.run(synthetic(), horizon=5, count=2, progress=lambda done, total, msg: seen.append((done, total, msg)))
    assert [s[0] for s in seen] == [0, 1, 2]
    assert all(s[1] == 2 for s in seen)
    assert all(isinstance(s[2], str) and s[2] for s in seen)


# ----------------------------------------------------------------- it travels with its model
def test_the_report_is_backed_up_and_rolled_back_with_the_model():
    assert "backtest_path" in train.ARTIFACTS, \
        "a report left behind by a different model reads as a measurement when it is a leftover"
    live = Path(settings.backtest_path)
    if not live.exists():
        pytest.skip("no accuracy report in this install")
    before = live.read_text(encoding="utf-8")

    dest = train.backup_dir()
    import shutil
    for name in train.ARTIFACTS:
        p = Path(getattr(settings, name))
        if p.exists():
            shutil.copy2(p, dest / p.name)
    assert (dest / live.name).exists()

    live.write_text(json.dumps({"kpis": {"day_wape": 1.23}}), encoding="utf-8")
    train.rollback(str(dest))
    assert live.read_text(encoding="utf-8") == before
    shutil.rmtree(dest, ignore_errors=True)


# ----------------------------------------------------------------- what the page gets
def test_the_accuracy_endpoint_serves_the_file_on_disk(client, tmp_path, monkeypatch):
    live = json.loads(Path(settings.backtest_path).read_text(encoding="utf-8"))
    r = client.get(f"{API}/forecast/accuracy")
    assert r.status_code == 200, r.text
    assert r.json()["kpis"] == live["kpis"]


def test_the_endpoint_says_so_when_no_report_has_been_generated(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backtest_path", str(tmp_path / "missing.json"))
    r = client.get(f"{API}/forecast/accuracy")
    assert r.status_code == 404
    assert "generated" in r.json()["detail"]
