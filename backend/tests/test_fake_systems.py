"""The planner's real HTTP integration code against a fake WMS and ERP on real ports.

Both run as real servers here: the planner calls the fake WMS/ERP over HTTP with their API keys, and the fake WMS
calls the planner's webhooks back over HTTP with the planner's key. Nothing is stubbed between them, so this is the
same code path a live connection takes (fake_systems/README.md).
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.core.config import settings
from tests.live import API, live, live_factory  # noqa: F401  (fixtures)
from tests.test_dataset_upload import small_model  # noqa: F401  (fixture)


def movements(live, **params):
    return live.get("/stock/movements", params={"limit": 1000, **params})


# ----------------------------------------------------------------- WMS
def test_inventory_sync_takes_the_wms_count(live):
    sku = live.get("/forecast/skus")[0]
    pid, wh, before = sku["product_id"], sku["warehouse_id"], sku["stock_on_hand"]
    live.fake.post("/control/wms/stock", json={"items": [{"product_id": pid, "warehouse_id": wh,
                                                           "stock_on_hand": before + 40}]})

    run = live.post("/integrations/sync/inventory")
    assert run["status"] == "OK" and run["rows"] == len(live.get("/forecast/skus")), run
    assert live.stock(pid, wh) == before + 40
    adj = movements(live, product_id=pid, warehouse_id=wh, kind="ADJUSTMENT")
    assert [(m["qty"], m["source"]) for m in adj] == [(40, "wms")]
    assert live.state["calls"]["GET /wms/inventory"] == 1


def test_approved_orders_reach_the_wms_and_shipping_comes_back_by_webhook(live):
    plan = live.get("/dispatch/plans/current")
    live.post(f"/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": "WH01"})
    sent = [x for x in live.get(f"/dispatch/plans/{plan['id']}/exports") if x["export_status"] == "SUCCESS"]
    assert sent and set(live.state["dispatch"]) == {x["order_id"] for x in sent}
    first = live.state["dispatch"][sent[0]["order_id"]]
    assert first["warehouse_id"] == "WH01" and first["qty"] == sent[0]["qty"] and first["trucks"]

    oid, pid = first["order_id"], int(first["product_id"])
    before = live.stock(pid, "WH01")
    out = live.fake.post("/control/wms/ship", json={"order_ids": [oid]}).json()
    assert out["shipped"] == [oid]
    assert out["confirmations"]["status"] == 200 and out["confirmations"]["body"]["shipped"] == 1
    # the WMS's own count after shipping matches ours, so its stock push changes nothing
    assert out["inventory"]["status"] == 200 and out["inventory"]["body"]["changed"] == 0

    assert live.stock(pid, "WH01") == pytest.approx(before - first["qty"])
    ship = movements(live, product_id=pid, warehouse_id="WH01", kind="SHIPMENT")
    assert [m["ref"] for m in ship] == [oid]
    assert oid not in {o["order_id"] for o in live.get("/integrations/confirmations/pending")["orders"]}


# ----------------------------------------------------------------- ERP
def order(oid, sku, minutes=0, qty=5):
    at = datetime.now().replace(microsecond=0) + timedelta(minutes=minutes)
    return {"order_id": oid, "order_timestamp": at.isoformat(), "customer_id": "C-FAKE", "customer_tier": "Standard",
            "product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "qty_ordered": qty,
            "due_date": (at + timedelta(days=2)).isoformat()}


def test_orders_are_pulled_once_and_can_be_pushed(live):
    sku = live.get("/forecast/skus")[0]
    live.fake.post("/control/erp/orders", json={"orders": [order("ERP-A", sku, 1), order("ERP-B", sku, 2)]})

    first = live.post("/integrations/sync/orders")
    again = live.post("/integrations/sync/orders")
    assert (first["status"], first["rows"]) == ("OK", 2)
    assert (again["status"], again["rows"]) == ("OK", 0)             # asked again: nothing is added twice
    lines = {ln["order_id"] for ln in live.get("/dispatch/plans/current")["lines"]}
    assert {"ERP-A", "ERP-B"} <= lines

    pushed = live.fake.post("/control/erp/orders", json={"orders": [order("ERP-C", sku, 3)], "push": True}).json()
    assert pushed["push"]["status"] == 200 and pushed["push"]["body"]["added"] == 1
    assert "ERP-C" in {ln["order_id"] for ln in live.get("/dispatch/plans/current")["lines"]}


def test_a_purchase_order_reaches_the_erp_and_keeps_its_reference(live):
    po = live.post("/integrations/purchase-orders", json={"days": 7, "urgent_only": True})[0]
    assert po["status"] == "SENT" and po["erp_reference"].startswith("ERP-PO-")
    held = live.state["purchase_orders"][po["po_ref"]]
    assert held["reference"] == po["erp_reference"] and held["warehouse_id"] == po["warehouse_id"]
    assert sum(ln["units"] for ln in held["lines"]) == po["total_units"]


def test_sales_sync_appends_the_erps_closed_days(live_factory, small_model, tmp_path):
    """The ERP's catalogue matches the small temporary history, so the real 37 MB file is never touched."""
    hist = pd.read_csv(settings.dataset_path, parse_dates=["date"])
    pairs = hist.drop_duplicates(["product_id", "warehouse_id"])
    cat = tmp_path / "catalogue"
    cat.mkdir()
    pairs[["warehouse_id", "city"]].drop_duplicates().to_csv(cat / "seed_warehouses.csv", index=False)
    pairs.drop_duplicates("product_id")[["product_id", "product_name", "category", "is_organic", "shelf_life_days",
                                         "weight_g"]].to_csv(cat / "seed_skus.csv", index=False)
    pairs[["product_id", "warehouse_id", "stock_on_hand"]].to_csv(cat / "seed_stock.csv", index=False)
    live = live_factory(data_dir=cat)

    run = live.post("/integrations/sync/sales")
    assert (run["status"], run["rows"]) == ("OK", len(pairs)), run
    after = pd.read_csv(settings.dataset_path, parse_dates=["date"])
    assert after["date"].max() == hist["date"].max() + pd.Timedelta(days=1)
    assert len(after) == len(hist) + len(pairs)


# ----------------------------------------------------------------- when it goes wrong
def test_a_wrong_key_or_a_system_that_is_down_fails_cleanly(live, monkeypatch):
    monkeypatch.setattr(settings, "wms_api_key", "not-the-key")
    run = live.post("/integrations/sync/inventory")
    assert run["status"] == "FAILED" and "401" in run["message"]

    live.fake.post("/control/erp/down")
    po = live.post("/integrations/purchase-orders", json={"days": 7, "urgent_only": True})[0]
    assert po["status"] == "FAILED" and "503" in po["error"]
    live.fake.post("/control/erp/up")
    again = live.post(f"/integrations/purchase-orders/{po['id']}/retry")
    assert again["status"] == "SENT" and again["erp_reference"]

    assert live.get("/integrations/status")["feeds"][0]["last"]["status"] == "FAILED"   # logged, app still up


def test_the_fake_systems_refuse_a_wrong_key(live):
    assert live.fake.get("/wms/inventory").status_code == 401
    assert live.fake.get("/erp/orders", headers={"Authorization": "Bearer wms-key"}).status_code == 401
    assert live.fake.get("/wms/inventory", headers={"Authorization": "Bearer wms-key"}).status_code == 200


def test_an_admin_connects_the_wms_in_the_app_instead_of_env(live, monkeypatch):
    """How a real installation connects: Systems > Connected systems, Test connection, switch on. No .env change."""
    for name in ("wms_base_url", "wms_api_key"):
        monkeypatch.setattr(settings, name, "")
    base = f"{str(live.fake.base_url).rstrip('/')}/wms"

    bad = live.post("/integrations/settings/test", json={"feed": "inventory", "base_url": base, "api_key": "nope"})
    assert bad["ok"] is False and "401" in bad["error"]
    good = live.post("/integrations/settings/test", json={"feed": "inventory", "base_url": base, "api_key": "wms-key"})
    assert good["ok"] is True and good["rows"] == len(live.state["stock"]) and good["missing"] == []

    r = live.app.put(f"{API}/integrations/settings/wms", json={"base_url": base, "api_key": "wms-key", "enabled": True})
    assert r.status_code == 200, r.text
    assert live.post("/integrations/sync/inventory")["status"] == "OK"
    assert live.get("/integrations/status")["dispatch_export"]["mode"] == "live"
