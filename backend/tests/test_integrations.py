import json

import httpx
import pytest

from app.core.config import settings
from app.integrations import clients
from app.modules.forecast.runtime import runtime
from tests.conftest import sign_in
from tests.test_dataset_upload import small_model  # noqa: F401  (fixture)

API = "/api/v1"


def stock_of(client, pid, wh):
    return next(s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json() if s["product_id"] == pid and s["warehouse_id"] == wh)


def test_status_lists_feeds_in_simulator_mode(client):
    d = client.get(f"{API}/integrations/status").json()
    assert [f["feed"] for f in d["feeds"]] == ["inventory", "orders", "sales", "purchasing", "dispatch"]
    assert all(f["mode"] == "simulator" for f in d["feeds"]) and d["dispatch_export"]["mode"] == "simulator"


def test_inventory_sync_changes_stock_and_plan(client):
    before = {(s["product_id"], s["warehouse_id"]): s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()}
    r = client.post(f"{API}/integrations/sync/inventory").json()
    assert r["status"] == "OK" and r["rows"] == len(before)
    after = {(s["product_id"], s["warehouse_id"]): s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()}
    assert after != before and runtime.stock_count() == len(before)
    st = client.get(f"{API}/integrations/status").json()
    assert st["feeds"][0]["last"]["status"] == "OK" and st["live_stock_skus"] == len(before)


def test_stock_feed_over_http_and_bad_rows_skipped(client):
    pid, wh = next((s["product_id"], s["warehouse_id"]) for s in client.get(f"{API}/forecast/skus").json())

    def handler(req: httpx.Request):
        assert req.url.path == "/inventory" and req.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"items": [
            {"product_id": pid, "warehouse_id": wh.lower(), "stock_on_hand": 4242},
            {"product_id": 999999, "warehouse_id": "WH01", "stock_on_hand": 5},      # unknown SKU
            {"product_id": pid, "warehouse_id": wh, "stock_on_hand": -3},            # impossible
        ]})

    clients.set_client("inventory", clients.HttpInventory("http://wms.test", "k", transport=httpx.MockTransport(handler)))
    r = client.post(f"{API}/integrations/sync/inventory").json()
    assert r["status"] == "OK" and r["rows"] == 1 and "2 skipped" in r["message"]
    assert stock_of(client, pid, wh) == 4242


def test_unreachable_system_is_logged_not_fatal(client):
    def handler(req):
        raise httpx.ConnectError("boom")

    clients.set_client("inventory", clients.HttpInventory("http://wms.test", "", transport=httpx.MockTransport(handler)))
    r = client.post(f"{API}/integrations/sync/inventory").json()
    assert r["status"] == "FAILED" and "Cannot reach" in r["message"]
    assert client.get(f"{API}/integrations/status").json()["feeds"][0]["last"]["status"] == "FAILED"


def test_order_sync_adds_orders_once_each(client):
    r = client.post(f"{API}/integrations/sync/orders").json()
    assert r["status"] == "OK" and r["rows"] == settings.simulated_orders_per_sync
    fixed = [{"order_id": "ERP-X1", "order_timestamp": "2025-12-31T10:00:00", "customer_id": "C1", "customer_tier": "Premium",
              "product_id": client.get(f"{API}/forecast/skus").json()[0]["product_id"],
              "warehouse_id": client.get(f"{API}/forecast/skus").json()[0]["warehouse_id"], "qty_ordered": 5, "due_date": "2026-01-03T10:00:00"}]

    class Fixed:
        async def fetch(self, since):
            return fixed + [{"order_id": "BAD", "product_id": "x"}]       # unusable row is skipped

    clients.set_client("orders", Fixed())
    a = client.post(f"{API}/integrations/sync/orders").json()
    b = client.post(f"{API}/integrations/sync/orders").json()
    assert a["rows"] == 1 and b["rows"] == 0           # same order is not added twice


def test_purchase_order_flow_and_scoping(client, anon):
    r = client.post(f"{API}/integrations/purchase-orders", json={"days": 7, "safety": True, "urgent_only": True})
    assert r.status_code == 200
    pos = r.json()
    assert pos and all(p["status"] == "SENT" and p["erp_reference"].startswith("ERP-PO-") for p in pos)
    assert pos[0]["total_units"] == sum(l["units"] for l in pos[0]["lines"]) > 0
    assert len(client.get(f"{API}/integrations/purchase-orders").json()) == len(pos)

    # an ERP that is down: the PO is kept as FAILED and can be retried
    class Down:
        async def create(self, po):
            return False, None, "ERP unreachable"

    clients.set_client("purchasing", Down())
    bad = client.post(f"{API}/integrations/purchase-orders", json={"days": 14, "safety": False, "warehouse_id": pos[0]["warehouse_id"]}).json()
    assert bad[0]["status"] == "FAILED" and bad[0]["error"] == "ERP unreachable"
    clients.set_client("purchasing", None)
    again = client.post(f"{API}/integrations/purchase-orders/{bad[0]['id']}/retry").json()
    assert again["status"] == "SENT" and again["attempts"] == 2

    # a planner raises orders for their own warehouse only
    sign_in(anon, "planner.wh01")
    assert anon.post(f"{API}/integrations/purchase-orders", json={"days": 7, "warehouse_id": "WH02"}).status_code == 403
    mine = anon.post(f"{API}/integrations/purchase-orders", json={"days": 7}).json()
    assert {p["warehouse_id"] for p in mine} == {"WH01"}
    assert {p["warehouse_id"] for p in anon.get(f"{API}/integrations/purchase-orders").json()} == {"WH01"}


def test_roles(client, anon):
    sign_in(anon, "viewer")
    assert anon.post(f"{API}/integrations/sync/inventory").status_code == 403
    assert anon.post(f"{API}/integrations/purchase-orders", json={"days": 7}).status_code == 403
    assert anon.get(f"{API}/integrations/status").status_code == 200


def test_webhooks_need_the_shared_key(client, anon, monkeypatch):
    body = {"items": []}
    assert anon.post(f"{API}/integrations/webhooks/inventory", json=body).status_code == 503      # off by default
    monkeypatch.setattr(settings, "integration_webhook_key", "s3cret")
    assert anon.post(f"{API}/integrations/webhooks/inventory", json=body).status_code == 401
    assert anon.post(f"{API}/integrations/webhooks/inventory", json=body, headers={"X-Integration-Key": "nope"}).status_code == 401
    s = client.get(f"{API}/forecast/skus").json()[0]
    item = {"product_id": s["product_id"], "warehouse_id": s["warehouse_id"], "stock_on_hand": 777}
    ok = anon.post(f"{API}/integrations/webhooks/inventory", json={"items": [item]}, headers={"X-Integration-Key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["applied"] == 1
    assert stock_of(client, s["product_id"], s["warehouse_id"]) == 777


def test_sales_feed_extends_history_without_retraining(small_model):
    import asyncio

    import pandas as pd

    from app.integrations import service

    rows = asyncio.run(clients.SimulatedSales().fetch(None))
    assert len(rows) == 6                                   # 3 SKUs x 2 warehouses, one new day each
    n, new_products, _ = service._append_sales(rows)
    merged = pd.read_csv(settings.dataset_path, parse_dates=["date"])
    assert n == 6 and new_products == [] and merged["date"].nunique() == 101
    assert runtime.frame["date"].max() == merged["date"].max()            # the forecast history moved forward
    bad = dict(rows[0], units_sold=-5)
    with pytest.raises(Exception):
        service._append_sales([bad])


def test_sales_sync_does_not_invent_data_in_simulator_mode(client):
    r = client.post(f"{API}/integrations/sync/sales").json()
    assert r["status"] == "OK" and r["rows"] == 0 and "not invented" in r["message"]
