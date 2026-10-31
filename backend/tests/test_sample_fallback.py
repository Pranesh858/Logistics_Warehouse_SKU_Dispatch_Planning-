"""A fresh clone has no full sales history, only the bundled sample. Uploads, retrains and the ERP sales feed must
still work there, and what they write becomes the history from then on.

Every test points the full history at a file that does not exist and the sample at a small one, with the model
files in a temp folder, so the real history and the committed model are never read or written.
"""
import json
import shutil
from pathlib import Path

import joblib
import pytest

from app.core.config import settings
from app.integrations import service as integrations
from app.ml import train
from app.ml.features import using_sample_dataset
from app.modules.forecast.runtime import runtime
from tests.test_dataset_upload import START, csv_bytes, make_rows, wait_done


@pytest.fixture()
def fresh_clone(tmp_path, monkeypatch):
    raw = make_rows([1, 2, 3], 100)
    sample = tmp_path / "sample.csv.gz"
    raw.assign(date=raw["date"].dt.strftime("%Y-%m-%d")).to_csv(sample, index=False, compression="gzip")
    art = tmp_path / "art"
    art.mkdir()
    shutil.copy(settings.model_metadata_path, art / "meta.json")
    meta = json.loads((art / "meta.json").read_text())
    # The model in use claims to be far better than anything 100 days can give, as the shipped three-year model
    # is next to the 120-day sample: a retrain here is refused unless the admin insists.
    meta.update(products=3, warehouses=2, training_date_range=["2023-01-01", "2025-04-10"],
                retrain_check={"wape_after": 0.001}, cv_metrics={"avg_wape": 0.001, "avg_mape_pct": 0.1})
    (art / "meta.json").write_text(json.dumps(meta))
    monkeypatch.setattr(settings, "retrain_estimators", 20)
    monkeypatch.setattr(settings, "dataset_path", str(tmp_path / "not-downloaded.csv"))
    monkeypatch.setattr(settings, "sample_dataset_path", str(sample))
    monkeypatch.setattr(settings, "model_path", str(art / "model.pkl"))
    monkeypatch.setattr(settings, "model_metadata_path", str(art / "meta.json"))
    monkeypatch.setattr(settings, "backtest_path", str(art / "backtest.json"))
    joblib.dump(train.fit(train.features_from_raw(raw)), art / "model.pkl")
    runtime.reload()
    assert using_sample_dataset()
    yield raw
    runtime.reload()


def test_retrain_on_the_sample_is_refused_then_goes_through_when_forced(client, fresh_clone):
    assert client.post("/api/v1/forecast/dataset/retrain").status_code == 200
    s = wait_done(client)
    assert s["state"] == "rejected", s
    assert s["kind"] == "history" and s["result"]["comparison"]["history_is_sample"] is True
    assert not Path(settings.dataset_path).exists(), "a refused retrain must not write anything"

    # "Use it anyway" after a refused retrain used to run the upload path and fail on a missing upload file.
    # Now it is refused up front ("Upload and check a dataset first"), and the retrain route takes force instead.
    assert client.post("/api/v1/forecast/dataset/apply?force=true").status_code == 422

    model_before = Path(settings.model_path).read_bytes()
    assert client.post("/api/v1/forecast/dataset/retrain?force=true").status_code == 200
    s = wait_done(client)
    assert s["state"] == "done", s
    assert Path(settings.model_path).read_bytes() != model_before
    written = Path(settings.dataset_path)
    assert written.exists() and not using_sample_dataset()
    assert len(train.pd.read_csv(written)) == len(fresh_clone)


def test_an_upload_on_the_sample_becomes_the_history(client, fresh_clone):
    later = START + train.pd.Timedelta(days=100)
    upload = make_rows([9], 60, start=later - train.pd.Timedelta(days=40)).pipe(
        lambda d: train.pd.concat([d, make_rows([1], 10, start=later)], ignore_index=True))
    r = client.post("/api/v1/forecast/dataset/check", files={"file": ("new.csv", csv_bytes(upload), "text/csv")})
    assert r.status_code == 200, r.text
    prev = r.json()["preview"]
    assert prev["errors"] == [] and prev["new_product_ids"] == [9]
    assert prev["current_history_to"] == "2025-04-10"          # the end of the sample

    assert client.post("/api/v1/forecast/dataset/apply?force=true").status_code == 200
    s = wait_done(client, limit=300)
    assert s["state"] == "done", s
    assert s["result"]["products"] == 4
    hist = train.pd.read_csv(settings.dataset_path, parse_dates=["date"])
    assert hist["date"].min() == START and 9 in set(hist["product_id"])


def test_rolling_back_a_retrain_made_on_the_sample_goes_back_to_the_sample(client, fresh_clone):
    assert client.post("/api/v1/forecast/dataset/retrain?force=true").status_code == 200
    s = wait_done(client)
    assert s["state"] == "done", s
    backup = Path(s["result"]["backup"])
    assert (backup / train.NO_FULL_HISTORY).exists()
    assert not using_sample_dataset()

    train.rollback(str(backup))
    assert not Path(settings.dataset_path).exists() and using_sample_dataset()
    shutil.rmtree(backup, ignore_errors=True)


def test_the_erp_sales_feed_adds_to_the_sample(fresh_clone):
    day = START + train.pd.Timedelta(days=100)
    rows = make_rows([1, 2], 1, start=day).assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d"))
    added, new_products, _ = integrations._append_sales(rows.to_dict("records"))
    assert added == len(rows) and new_products == []
    hist = train.pd.read_csv(settings.dataset_path, parse_dates=["date"])
    assert len(hist) == len(fresh_clone) + len(rows) and hist["date"].max() == day
