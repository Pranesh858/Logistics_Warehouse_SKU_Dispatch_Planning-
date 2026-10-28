"""Data typed in by a person: stock counts and new orders.

A warehouse with no WMS still has to be able to change what the system believes. What matters here is that the
change is real (it reaches the plan), that it is kept (it is in the database, not just in memory) and that
nobody can change a warehouse that is not theirs.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.audit import AuditEntry
from app.core.database import AsyncSessionLocal
from app.integrations import service as integration_service
from app.integrations.models import StockLevel
from app.modules.forecast.runtime import runtime
from tests.conftest import sign_in

API = "/api/v1"


def a_sku(client, warehouse=None):
    rows = client.get(f"{API}/forecast/skus").json()
    return next(r for r in rows if warehouse is None or r["warehouse_id"] == warehouse)


def stock_of(client, pid, wh):
    return next(s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()
                if s["product_id"] == pid and s["warehouse_id"] == wh)


def order(order_id, sku, qty, tier="Standard"):
    now = datetime.now().replace(microsecond=0)
    return {"order_id": order_id, "order_timestamp": now.isoformat(), "customer_id": "C-MANUAL",
            "customer_tier": tier, "product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"],
            "qty_ordered": qty, "due_date": (now + timedelta(days=2)).isoformat()}


def line(plan, order_id):
    return next(l for l in plan["lines"] if l["order_id"] == order_id)


def test_a_stock_count_replaces_what_was_on_hand(client):
    sku = a_sku(client)
    r = client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": 321}],
        "reason": "cycle count aisle 4"})
    assert r.status_code == 200 and r.json() == {"applied": 1, "changed": 1, "skipped": 0}
    assert stock_of(client, sku["product_id"], sku["warehouse_id"]) == 321


def test_the_count_is_kept_in_the_database_and_survives_a_restart(client):
    sku = a_sku(client)
    client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": 654}]})

    async def stored():
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(StockLevel).where(
                StockLevel.product_id == sku["product_id"], StockLevel.warehouse_id == sku["warehouse_id"]))).scalar_one()
            return row.qty, row.source

    assert client.portal.call(stored) == (654, "manual")

    # what a restart does: the in-memory view is gone, the overlay is read back from the table
    runtime.set_live_stock({})
    assert stock_of(client, sku["product_id"], sku["warehouse_id"]) != 654

    async def reload():
        async with AsyncSessionLocal() as db:
            return await integration_service.load_overlay(db)

    assert client.portal.call(reload) >= 1
    assert stock_of(client, sku["product_id"], sku["warehouse_id"]) == 654


def test_the_audit_trail_says_who_and_why(client):
    sku = a_sku(client)
    client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": 10}],
        "reason": "damaged pallet written off"})

    async def audit():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(AuditEntry).where(AuditEntry.action == "stock_set"))).scalars().all()

    rows = client.portal.call(audit)
    assert len(rows) == 1 and rows[0].username == "admin" and "damaged pallet written off" in rows[0].detail


def test_unknown_sku_or_negative_stock_is_refused_with_a_reason(client):
    sku = a_sku(client)
    unknown = client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": 987654, "warehouse_id": sku["warehouse_id"], "stock_on_hand": 5}]})
    assert unknown.status_code == 422 and "exist" in unknown.json()["detail"]
    negative = client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": -1}]})
    assert negative.status_code == 422
    assert client.post(f"{API}/integrations/stock", json={"items": []}).status_code == 422


def test_a_good_row_is_applied_even_when_another_row_is_not_known(client):
    sku = a_sku(client)
    r = client.post(f"{API}/integrations/stock", json={"items": [
        {"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": 77},
        {"product_id": 987654, "warehouse_id": sku["warehouse_id"], "stock_on_hand": 5}]})
    assert r.json() == {"applied": 1, "changed": 1, "skipped": 1}


def test_a_planner_can_only_count_their_own_warehouse(client, anon):
    mine = a_sku(client, "WH01")
    other = a_sku(client, "WH02")
    sign_in(anon, "planner.wh01")
    refused = anon.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": other["product_id"], "warehouse_id": "WH02", "stock_on_hand": 1}]})
    assert refused.status_code == 403
    ok = anon.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": mine["product_id"], "warehouse_id": "wh01", "stock_on_hand": 42}]})
    assert ok.status_code == 200                       # lower-case ids are accepted
    assert stock_of(anon, mine["product_id"], "WH01") == 42


def test_a_viewer_cannot_change_stock(client, anon):
    sku = a_sku(client)
    sign_in(anon, "viewer")
    r = anon.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "stock_on_hand": 1}]})
    assert r.status_code == 403


def test_a_new_order_and_then_a_stock_count_change_the_plan(client):
    """The whole point of a live database: type something in, and what the system recommends moves with it."""
    sku = a_sku(client)
    pid, wh = sku["product_id"], sku["warehouse_id"]
    client.post(f"{API}/integrations/stock", json={"items": [{"product_id": pid, "warehouse_id": wh, "stock_on_hand": 30}]})

    plan = client.post(f"{API}/dispatch/orders", json={"orders": [order("MAN-TEST-1", sku, 100)]}).json()
    short = line(plan, "MAN-TEST-1")
    assert short["qty_allocated"] <= 30 and short["qty_short"] >= 70          # only 30 on the shelf

    client.post(f"{API}/integrations/stock", json={"items": [{"product_id": pid, "warehouse_id": wh, "stock_on_hand": 5000}]})
    after = line(client.get(f"{API}/dispatch/plans/current").json(), "MAN-TEST-1")
    assert after["qty_allocated"] == 100 and after["qty_short"] == 0          # goods in -> the order is filled


def test_the_same_order_id_cannot_be_typed_in_twice(client):
    sku = a_sku(client)
    assert client.post(f"{API}/dispatch/orders", json={"orders": [order("MAN-TEST-2", sku, 5)]}).status_code == 200
    again = client.post(f"{API}/dispatch/orders", json={"orders": [order("MAN-TEST-2", sku, 5)]})
    assert again.status_code == 409
