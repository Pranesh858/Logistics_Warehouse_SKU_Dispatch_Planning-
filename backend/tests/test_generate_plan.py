"""Plans are built when a planner presses Generate plan, not every time something happens.

Each order sync, stock count, receipt or shipment used to rebuild the plan: 52 of 56 plans in the demo were
replaced before anyone looked at them. Now those events are only noted, the plan says it is out of date and why,
and Generate plan (POST /dispatch/plans/recalculate) builds the next one.
"""
import pytest

from app.core.config import settings

API = "/api/v1"


@pytest.fixture(autouse=True)
def manual(monkeypatch):
    monkeypatch.setattr(settings, "auto_replan", False)
    monkeypatch.setattr(settings, "integration_webhook_key", "k")


def current(c):
    return c.get(f"{API}/dispatch/plans/current").json()


def an_order(c, oid="G1", qty=3):
    line = current(c)["lines"][0]
    return {"order_id": oid, "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C9", "customer_tier": "Premium",
            "product_id": line["product_id"], "warehouse_id": line["warehouse_id"], "qty_ordered": qty,
            "due_date": "2026-02-03T10:00:00"}


def test_new_orders_and_a_stock_count_do_not_make_a_plan(client):
    before = current(client)
    assert before["changes"] == []
    r = client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G1"), an_order(client, "G2")]})
    assert r.status_code == 200
    assert r.json()["id"] == before["id"]                         # same plan comes back, not a new one
    item = {"product_id": before["lines"][0]["product_id"], "warehouse_id": before["lines"][0]["warehouse_id"], "stock_on_hand": 999}
    ok = client.post(f"{API}/integrations/webhooks/inventory", json={"items": [item]}, headers={"X-Integration-Key": "k"})
    assert ok.status_code == 200 and ok.json()["applied"] == 1

    now = current(client)
    assert now["id"] == before["id"] and now["version"] == before["version"]
    assert [c["text"] for c in now["changes"]] == ["2 new orders", "stock count changed for 1 SKU"]
    assert {"G1", "G2"}.isdisjoint(l["order_id"] for l in now["lines"])
    assert len(client.get(f"{API}/dispatch/plans").json()) == 1


def test_more_orders_add_up_in_one_line(client):
    client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G1")]})
    client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G2"), an_order(client, "G3")]})
    assert [c["text"] for c in current(client)["changes"]] == ["3 new orders"]


def test_generate_plan_takes_them_in_and_clears_the_list(client):
    before = current(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G1")]})
    r = client.post(f"{API}/dispatch/plans/recalculate")
    assert r.status_code == 200
    plan = r.json()
    assert plan["version"] == before["version"] + 1 and plan["trigger"] == "recalculate"
    assert "G1" in {l["order_id"] for l in plan["lines"]}
    assert plan["changes"] == [] and current(client)["changes"] == []


def test_an_approved_plan_lists_no_changes(client):
    plan = current(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G1")]})
    done = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"}).json()
    assert done["changes"] == []
    # approving still leaves a fresh plan for what is open, and that one includes the new order
    nxt = current(client)
    assert nxt["id"] != plan["id"] and nxt["changes"] == []
    assert "G1" in {l["order_id"] for l in nxt["lines"]}


def test_an_old_plan_cannot_promise_stock_that_has_gone(client):
    """The plan on screen may be older than the last stock count; approval checks the stock as it is now."""
    plan = current(client)
    line = next(l for l in plan["lines"] if l["qty_allocated"] > 0)
    item = {"product_id": line["product_id"], "warehouse_id": line["warehouse_id"], "stock_on_hand": 0}
    client.post(f"{API}/integrations/webhooks/inventory", json={"items": [item]}, headers={"X-Integration-Key": "k"})
    r = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"})
    assert r.status_code == 422, r.text
    assert "press Generate plan" in r.json()["detail"]
    assert current(client)["changes"][0]["kind"] == "stock_update"


def test_auto_replan_brings_back_the_old_behaviour(client, monkeypatch):
    monkeypatch.setattr(settings, "auto_replan", True)
    before = current(client)
    r = client.post(f"{API}/dispatch/orders", json={"orders": [an_order(client, "G1")]})
    assert r.json()["version"] == before["version"] + 1
    assert "G1" in {l["order_id"] for l in r.json()["lines"]} and r.json()["changes"] == []
