"""ERPNext as the ERP, against a fake ERPNext that answers the same REST paths a real site does.

The shapes below were taken from a live ERPNext v16 site (scripts/erpnext_seed.py); the fake only keeps what the
clients read, so a change on our side that would break against the real thing breaks here too.
"""
import asyncio
import json
from urllib.parse import unquote

import httpx
import pytest

from app.integrations import clients, config_store, erpnext
from app.integrations.clients import IntegrationError

API = "/api/v1"
KEY = "k1:s1"


class FakeErpNext:
    """Sales orders in, purchase orders out, warehouses named "<id> - DD"."""

    def __init__(self, orders: list[dict] | None = None):
        self.orders = {o["name"]: o for o in orders or []}
        self.pos: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"token {KEY}"
        path = unquote(request.url.path)
        params = dict(request.url.params)
        self.calls.append((request.method, path, params))
        filters = json.loads(params.get("filters", "[]"))
        if request.method == "GET" and path == "/api/resource/Sales Order":
            return httpx.Response(200, json={"data": [{"name": n} for n in self.orders]})
        if request.method == "GET" and path.startswith("/api/resource/Sales Order/"):
            return httpx.Response(200, json={"data": self.orders[path.rsplit("/", 1)[1]]})
        if request.method == "GET" and path == "/api/resource/Warehouse":
            return httpx.Response(200, json={"data": [{"name": f"WH0{i} - DD", "company": "Dispatch Demo"} for i in range(1, 7)]})
        if request.method == "GET" and path == "/api/resource/Purchase Order":
            ref = next(f[2] for f in filters if f[0] == "order_confirmation_no")
            return httpx.Response(200, json={"data": [{"name": n} for n, p in self.pos.items() if p["order_confirmation_no"] == ref]})
        if request.method == "POST" and path == "/api/resource/Purchase Order":
            doc = json.loads(request.content)
            name = f"PUR-ORD-2026-{len(self.pos) + 1:05d}"
            self.pos[name] = {**doc, "name": name, "docstatus": 0}
            return httpx.Response(200, json={"data": self.pos[name]})
        if request.method == "POST" and path == "/api/method/frappe.client.submit":
            doc = json.loads(request.content)["doc"]
            self.pos[doc["name"]]["docstatus"] = 1
            return httpx.Response(200, json={"message": self.pos[doc["name"]]})
        return httpx.Response(404, json={"exception": f"no route {request.method} {path}"})

    def transport(self):
        return httpx.MockTransport(self.handler)


def sales_order(name, group, lines, created="2026-11-02 08:15:42.123456"):
    return {"name": name, "creation": created, "customer": f"Cust {name}", "customer_group": group,
            "set_warehouse": "WH01 - DD", "delivery_date": "2026-11-04", "docstatus": 1, "status": "To Deliver and Bill",
            "items": [{"idx": i + 1, "item_code": code, "qty": qty, "stock_qty": qty, "warehouse": wh,
                       "delivery_date": "2026-11-03"} for i, (code, qty, wh) in enumerate(lines)]}


# ----------------------------------------------------------------- the clients on their own
def test_each_item_line_becomes_one_planner_order():
    fake = FakeErpNext([sales_order("SO-1", "Premium", [("271", 2, "WH01 - DD"), ("ABC-1", 5, "WH01 - DD"), ("135", 3, "WH02 - DD")]),
                        sales_order("SO-2", "Commercial", [("39", 4, None)])])
    rows = asyncio.run(erpnext.ErpNextOrders("http://erp", KEY, transport=fake.transport()).fetch(None))
    assert [r["order_id"] for r in rows] == ["SO-1-1", "SO-1-3", "SO-2-1"]        # ABC-1 is not one of our products
    first = rows[0]
    assert first == {"order_id": "SO-1-1", "order_timestamp": "2026-11-02T08:15:42", "customer_id": "Cust SO-1",
                     "customer_tier": "Premium", "product_id": 271, "warehouse_id": "WH01", "qty_ordered": 2.0,
                     "due_date": "2026-11-03T23:59:00"}
    assert rows[1]["warehouse_id"] == "WH02"
    assert rows[2]["customer_tier"] == "Standard" and rows[2]["warehouse_id"] == "WH01"   # other group; header warehouse


def test_only_submitted_open_orders_are_asked_for_with_a_lookback():
    from datetime import datetime
    fake = FakeErpNext()
    asyncio.run(erpnext.ErpNextOrders("http://erp", KEY, transport=fake.transport()).fetch(datetime(2026, 11, 2, 9, 0)))
    filters = json.loads(fake.calls[0][2]["filters"])
    assert ["docstatus", "=", 1] in filters
    assert ["status", "not in", ["Closed", "Completed", "On Hold"]] in filters
    assert ["creation", ">=", "2026-10-31 09:00:00"] in filters                  # two days back; known ids are skipped


def test_a_purchase_order_is_submitted_once_with_whole_units():
    fake = FakeErpNext()
    client = erpnext.ErpNextPurchasing("http://erp", KEY, transport=fake.transport())
    po = {"po_ref": "PO-WH03-1", "warehouse_id": "WH03", "lines": [{"product_id": 7, "units": 12.2}, {"product_id": 9, "units": 0}]}
    assert asyncio.run(client.create(po)) == (True, "PUR-ORD-2026-00001", None)
    made = fake.pos["PUR-ORD-2026-00001"]
    assert made["docstatus"] == 1 and made["set_warehouse"] == "WH03 - DD" and made["order_confirmation_no"] == "PO-WH03-1"
    assert made["items"] == [{"item_code": "7", "qty": 13, "schedule_date": made["schedule_date"], "warehouse": "WH03 - DD"}]
    assert asyncio.run(client.create(po)) == (True, "PUR-ORD-2026-00001", None)  # sent again: the same order
    assert len(fake.pos) == 1


def test_clear_errors_for_a_bad_key_or_an_unknown_warehouse():
    fake = FakeErpNext()
    ok, ref, err = asyncio.run(erpnext.ErpNextPurchasing("http://erp", "only-a-key", transport=fake.transport()).create(
        {"po_ref": "X", "warehouse_id": "WH01", "lines": []}))
    assert not ok and "key:secret" in err
    ok, ref, err = asyncio.run(erpnext.ErpNextPurchasing("http://erp", KEY, transport=fake.transport()).create(
        {"po_ref": "Y", "warehouse_id": "WH99", "lines": [{"product_id": 1, "units": 1}]}))
    assert not ok and "WH99" in err
    with pytest.raises(IntegrationError, match="not read from ERPNext"):
        asyncio.run(erpnext.ErpNextSales("http://erp", KEY).fetch(None))


# ----------------------------------------------------------------- through the app
@pytest.fixture()
def erp_connected(client, monkeypatch):
    """The ERP connected in the app as ERPNext, its order client talking to a fake site."""
    fake = FakeErpNext()

    class Orders(erpnext.ErpNextOrders):
        def __init__(self, base, key, transport=None, mapping=None):
            super().__init__(base, key, transport=fake.transport(), mapping=mapping)
    monkeypatch.setattr(erpnext, "ErpNextOrders", Orders)
    r = client.put(f"{API}/integrations/settings/erp",
                   json={"kind": "erpnext", "base_url": "http://erp", "api_key": KEY, "enabled": True})
    assert r.status_code == 200, r.text
    yield fake
    config_store.clear()


def test_an_admin_connects_erpnext_and_its_orders_reach_the_plan(client, erp_connected):
    saved = client.get(f"{API}/integrations/settings").json()["erp"]
    assert saved["kind"] == "erpnext" and saved["has_key"] and "api_key" not in saved
    assert isinstance(clients.order_source(), erpnext.ErpNextOrders)
    assert isinstance(clients.purchase_sink(), erpnext.ErpNextPurchasing)

    sku = next(s for s in client.get(f"{API}/forecast/skus").json() if s["warehouse_id"] == "WH01")
    erp_connected.orders = {"SO-9": sales_order("SO-9", "Premium", [(str(sku["product_id"]), 2, "WH01 - DD")])}
    run = client.post(f"{API}/integrations/sync/orders").json()
    assert run["status"] == "OK" and run["rows"] == 1, run
    assert "SO-9-1" in {ln["order_id"] for ln in client.get(f"{API}/dispatch/plans/current").json()["lines"]}
    assert client.post(f"{API}/integrations/sync/orders").json()["rows"] == 0       # pulled once


def test_erpnext_is_only_offered_for_the_erp(client):
    r = client.put(f"{API}/integrations/settings/wms", json={"kind": "erpnext", "base_url": "http://x", "enabled": False})
    assert r.status_code == 422
