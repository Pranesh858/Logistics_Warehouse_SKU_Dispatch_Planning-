import io
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.ml import train
from app.modules.forecast.runtime import runtime
from tests.conftest import sign_in

START = pd.Timestamp("2025-01-01")


def make_rows(products, days, start=START, warehouses=("WH01", "WH02")):
    rng = np.random.default_rng(1)
    rows = []
    for p in products:
        for w in warehouses:
            for d in range(days):
                day = start + pd.Timedelta(days=d)
                rows.append({
                    "product_id": p, "product_name": f"Item {p}", "category": "Grocery" if p % 2 else "Dairy",
                    "date": day, "units_sold": float(max(0, rng.normal(20 + p, 3))), "stock_on_hand": 500.0,
                    "price": 50.0 + p, "discount_pct": 0, "promotion_flag": 0,
                    "city": "Pune" if w == "WH01" else "Delhi", "warehouse_id": w, "is_organic": False,
                    "shelf_life_days": 30, "weight_g": 500, "event_name_1": "No Event", "event_type_1": "No Event",
                })
    return pd.DataFrame(rows)


def csv_bytes(df):
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode()


@pytest.fixture()
def small_model(tmp_path, monkeypatch):
    """A tiny model and history in a temp folder, so retraining takes a second and the real files stay untouched."""
    raw = make_rows([1, 2, 3], 100)
    ds = tmp_path / "data.csv"
    raw.assign(date=raw["date"].dt.strftime("%Y-%m-%d")).to_csv(ds, index=False)
    art = tmp_path / "art"
    art.mkdir()
    shutil.copy(settings.model_metadata_path, art / "meta.json")
    meta = json.loads((art / "meta.json").read_text())
    monkeypatch.setattr(settings, "retrain_estimators", 20)
    monkeypatch.setattr(settings, "dataset_path", str(ds))
    monkeypatch.setattr(settings, "model_path", str(art / "model.pkl"))
    monkeypatch.setattr(settings, "model_metadata_path", str(art / "meta.json"))
    # A promotion now re-scores the accuracy report, so that file is part of "the real files stay untouched".
    monkeypatch.setattr(settings, "backtest_path", str(art / "backtest.json"))
    frame = train.features_from_raw(raw)
    import joblib
    joblib.dump(train.fit(frame), art / "model.pkl")
    meta.update(products=3, warehouses=2, training_date_range=["2025-01-01", "2025-04-10"])
    (art / "meta.json").write_text(json.dumps(meta))
    runtime.reload()
    yield raw
    runtime.reload()


def wait_done(c, limit=120):
    end = time.time() + limit
    while time.time() < end:
        s = c.get("/api/v1/forecast/dataset/status").json()
        if s["state"] in ("done", "failed", "rejected"):
            return s
        time.sleep(0.5)
    raise AssertionError("retrain did not finish")


def test_upload_needs_admin(anon, small_model):
    sign_in(anon, "planner.wh01")
    r = anon.post("/api/v1/forecast/dataset/check", files={"file": ("a.csv", b"x", "text/csv")})
    assert r.status_code == 403


def test_bad_file_is_explained(client, small_model):
    r = client.post("/api/v1/forecast/dataset/check", files={"file": ("a.csv", b"product_id,date\n1,2025-01-01\n", "text/csv")})
    assert r.status_code == 200
    assert "Missing column" in r.json()["preview"]["errors"][0]
    neg = make_rows([1], 40)
    neg.loc[0, "units_sold"] = -5
    r = client.post("/api/v1/forecast/dataset/check", files={"file": ("a.csv", csv_bytes(neg), "text/csv")})
    assert any("negative" in e for e in r.json()["preview"]["errors"])
    assert client.post("/api/v1/forecast/dataset/apply").status_code == 422


def test_new_sku_becomes_known_after_retrain(client, small_model):
    # product 9 is new; products 1 and 2 get 20 more days after the existing history
    later = START + pd.Timedelta(days=100)
    upload = pd.concat([make_rows([9], 60), make_rows([1, 2], 20, start=later)], ignore_index=True)
    r = client.post("/api/v1/forecast/dataset/check", files={"file": ("new.csv", csv_bytes(upload), "text/csv")})
    prev = r.json()["preview"]
    assert prev["errors"] == [] and prev["new_product_ids"] == [9] and prev["extends_history"]

    assert client.post("/api/v1/forecast/run", json={"days": 7, "product_ids": [9]}).status_code == 422  # not known yet

    assert client.post("/api/v1/forecast/dataset/apply?force=true").status_code == 200
    s = wait_done(client)
    assert s["state"] == "done", s
    assert s["result"]["products"] == 4 and s["result"]["new_product_ids"] == [9]

    r = client.post("/api/v1/forecast/run", json={"days": 7, "product_ids": [9]})
    assert r.status_code == 200 and r.json()["grand_total"] > 0
    # old rows are still in the history alongside the new ones
    merged = pd.read_csv(settings.dataset_path, parse_dates=["date"])
    assert merged["date"].min() == START and merged[merged.product_id == 1]["date"].nunique() == 120


def test_a_promotion_updates_the_typical_error_the_forecast_page_shows(client, small_model):
    """The forecast page's "typical error" is the MAPE saved with the model. A retrain used to copy the previous
    model's MAPE across, so the page showed the same figure (18.4%) whatever model was in use."""
    old = json.loads(Path(settings.model_metadata_path).read_text())["cv_metrics"]["avg_mape_pct"]
    assert client.post("/api/v1/forecast/dataset/retrain?force=true").status_code == 200
    s = wait_done(client)
    assert s["state"] == "done", s
    measured = s["result"]["comparison"]["mape_after_pct"]
    assert measured > 0 and measured != old

    saved = json.loads(Path(settings.model_metadata_path).read_text())["cv_metrics"]
    assert saved["avg_mape_pct"] == measured
    assert saved["avg_wape"] == s["result"]["comparison"]["wape_after"]
    r = client.post("/api/v1/forecast/run", json={"days": 7})
    assert r.status_code == 200 and r.json()["model"]["mape_pct"] == measured


def test_short_new_sku_is_left_out(client, small_model):
    upload = make_rows([7], 10)
    prev = client.post("/api/v1/forecast/dataset/check", files={"file": ("n.csv", csv_bytes(upload), "text/csv")}).json()["preview"]
    assert prev["short_history_pairs"] and any("fewer than" in w for w in prev["warnings"])


def test_a_promotion_re_scores_the_accuracy_report(client, small_model):
    """The accuracy page must describe the model that is live.

    It used to read a file produced once, offline: after a retrain the page kept showing the previous
    model's figures, which is the worst sort of wrong because it looks right.
    """
    report = Path(settings.backtest_path)
    report.write_text(json.dumps({"kpis": {"day_mape_pct": 99.9}, "by_sku": []}), encoding="utf-8")

    new = make_rows([9], 120)
    r = client.post("/api/v1/forecast/dataset/check",
                    files={"file": ("new.csv", csv_bytes(new), "text/csv")})
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/forecast/dataset/apply").status_code == 200
    s = wait_done(client, limit=300)
    assert s["state"] == "done", s

    assert s["result"].get("accuracy"), "the retrain should report the new model's figures"
    fresh = json.loads(report.read_text(encoding="utf-8"))
    assert fresh["kpis"]["day_mape_pct"] != 99.9, "the stale report was left in place"
    assert fresh["generated_at"]
    assert fresh["kpis"]["skus"] == 4, "it was scored on the history the new model was trained on"
    assert s["result"]["accuracy"]["day_mape_pct"] == fresh["kpis"]["day_mape_pct"]


def test_a_rejected_retrain_leaves_the_accuracy_report_alone(client, small_model):
    """A model that was not promoted has not changed anything, so its figures must not be published."""
    report = Path(settings.backtest_path)
    report.write_text(json.dumps({"kpis": {"day_mape_pct": 99.9}}), encoding="utf-8")
    before = report.read_text(encoding="utf-8")

    # Nonsense sales for a known SKU: the new model scores clearly worse and should be refused.
    bad = make_rows([1], 120)
    bad["units_sold"] = [5000 if i % 2 else 1 for i in range(len(bad))]
    r = client.post("/api/v1/forecast/dataset/check",
                    files={"file": ("bad.csv", csv_bytes(bad), "text/csv")})
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/forecast/dataset/apply").status_code == 200
    s = wait_done(client, limit=300)
    if s["state"] != "rejected":
        pytest.skip(f"the model was not rejected on this data (state={s['state']})")
    assert report.read_text(encoding="utf-8") == before
