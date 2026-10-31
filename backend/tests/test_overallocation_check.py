"""The over-allocation guard must not count goods that have already shipped.

Once the WMS confirms an order shipped, its units have left and the shelf figure shows it, so the engine hands the
rest of the shelf out again. The guard used to add the shipped units back on top, report over-allocation where
there was none, and throw away every new plan from then on. It was reached because a shipped order the ERP
listed again was imported as a new open order.
"""
import pandas as pd

from app.core.config import settings
from app.modules.dispatch import engine

API = "/api/v1"
WH = "WH01"


def test_guard_counts_what_the_ledger_still_holds():
    stock = pd.DataFrame([{"product_id": 1, "warehouse_id": WH, "city": "X", "stock_on_hand": 6.0}])
    plan = pd.DataFrame([
        {"order_id": "SHIPPED", "product_id": 1, "warehouse_id": WH, "qty_allocated": 4.0, "status": "COMMITTED"},
        {"order_id": "HELD", "product_id": 1, "warehouse_id": WH, "qty_allocated": 2.0, "status": "COMMITTED"},
        {"order_id": "NEW", "product_id": 1, "warehouse_id": WH, "qty_allocated": 4.0, "status": "FULL"},
    ])
    ledger = pd.DataFrame([
        {"order_id": "SHIPPED", "product_id": 1, "warehouse_id": WH, "qty_committed": 4.0, "qty_reserved": 0.0},
        {"order_id": "HELD", "product_id": 1, "warehouse_id": WH, "qty_committed": 2.0, "qty_reserved": 2.0},
    ])
    assert engine.verify_no_overallocation(plan, stock, ledger).empty           # 2 held + 4 new = 6 on the shelf
    over = plan.assign(qty_allocated=[4.0, 2.0, 5.0])
    assert len(engine.verify_no_overallocation(over, stock, ledger)) == 1       # a real excess is still caught


def test_a_shipped_order_the_erp_sends_again_is_not_planned_again(client, monkeypatch):
    """What happened in the demo: an order shipped, the ERP listed it again on its next sync, it came back as a new
    open order, and the guard counted its units twice. The plan for the SKU was thrown away from then on."""
    monkeypatch.setattr(settings, "integration_webhook_key", "test-key")
    skus = [s for s in client.get(f"{API}/forecast/skus").json() if s["warehouse_id"] == WH]
    ordered = {ln["product_id"] for ln in client.get(f"{API}/dispatch/plans/current").json()["lines"]
               if ln["warehouse_id"] == WH}
    pid = next(s["product_id"] for s in skus if s["product_id"] not in ordered)   # no other orders compete
    for t in client.get(f"{API}/dispatch/trucks").json():
        client.patch(f"{API}/dispatch/trucks/{t['id']}", json={"capacity_units": 100000})
    assert client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": pid, "warehouse_id": WH, "stock_on_hand": 10}]}).status_code == 200

    def order(oid, qty):
        return {"orders": [{"order_id": oid, "order_timestamp": "2020-01-01T00:00:00", "customer_id": "C-T",
                            "customer_tier": "Premium", "product_id": pid, "warehouse_id": WH, "qty_ordered": qty,
                            "due_date": "2020-01-01T06:00:00"}]}

    def from_erp(body):
        return client.post(f"{API}/integrations/webhooks/orders", json=body, headers={"X-Integration-Key": "test-key"})

    assert from_erp(order("SHIP-A", 4)).json()["added"] == 1
    plan = client.get(f"{API}/dispatch/plans/current").json()
    assert client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": WH}).status_code == 200
    r = client.post(f"{API}/integrations/confirmations", json={"items": [{"order_id": "SHIP-A"}]})
    assert r.status_code == 200, r.text
    assert next(s for s in client.get(f"{API}/forecast/skus").json()
                if s["product_id"] == pid and s["warehouse_id"] == WH)["stock_on_hand"] == 6

    again = from_erp(order("SHIP-A", 4)).json()                       # the ERP lists the shipped order again
    assert (again["added"], again["skipped"]) == (0, 1)
    assert client.post(f"{API}/dispatch/orders", json=order("SHIP-A", 4)).status_code == 409

    assert from_erp(order("SHIP-B", 6)).json()["added"] == 1           # takes the 6 still on the shelf
    lines = client.get(f"{API}/dispatch/plans/current").json()["lines"]
    assert "SHIP-A" not in {ln["order_id"] for ln in lines}
    assert next(ln for ln in lines if ln["order_id"] == "SHIP-B")["qty_allocated"] == 6
