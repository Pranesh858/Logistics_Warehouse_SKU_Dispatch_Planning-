"""GET /kpis: the sums, who may see what, and that no figure is invented when there is nothing to measure."""
import asyncio
from datetime import date, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.dispatch.models import LedgerEntry
from app.modules.kpis import service
from tests.conftest import sign_in

API = "/api/v1"
WH = "WH01"


def kpis(client, **params):
    r = client.get(f"{API}/kpis", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def current(client):
    return client.get(f"{API}/dispatch/plans/current").json()


def free_sku(client, wh=WH):
    ordered = {l["product_id"] for l in current(client)["lines"] if l["warehouse_id"] == wh}
    return next(s for s in client.get(f"{API}/forecast/skus").json()
                if s["warehouse_id"] == wh and s["product_id"] not in ordered and s["stock_on_hand"] >= 20)


def order(oid, sku, qty, tier="Premium", due=None):
    return {"order_id": oid, "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C-K", "customer_tier": tier,
            "product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "qty_ordered": qty,
            "due_date": due or "2099-01-01T10:00:00"}


# ----------------------------------------------------------------- the sums
def test_the_rates_on_known_lines():
    rows = [{"qty_ordered": 10, "planned": 10, "status": "FULL", "at_risk": False},
            {"qty_ordered": 10, "planned": 5, "status": "PARTIAL", "at_risk": True},
            {"qty_ordered": 20, "planned": 0, "status": "BACKORDERED", "at_risk": True},
            {"qty_ordered": 10, "planned": 0, "status": "HELD", "at_risk": False}]
    s = service.summarise(rows)
    assert s["fill_rate_pct"] == 30.0                          # 15 of 50 units
    assert s["order_fill_rate_pct"] == 25.0                    # 1 of 4 orders
    assert (s["partial"], s["held"], s["backordered"], s["at_risk"]) == (1, 1, 1, 2)


def test_nothing_to_measure_is_not_zero():
    s = service.summarise([])
    assert s["fill_rate_pct"] is None and s["order_fill_rate_pct"] is None
    assert service.service_level(None)["met"] is None


def test_the_target_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "service_level_target_pct", 80.0)
    assert service.service_level(80.0) == {"target_pct": 80.0, "measure": "fill_rate", "value_pct": 80.0, "met": True}
    assert service.service_level(79.9)["met"] is False


def test_figures_match_the_current_plan(client):
    k, plan = kpis(client), current(client)
    assert k["plan_version"] == plan["version"]
    assert k["orders"] == plan["summary"]["orders"]
    assert k["units_ordered"] == plan["summary"]["units_ordered"]
    assert k["fill_rate_pct"] == plan["summary"]["coverage_pct"]
    assert k["at_risk"] == plan["summary"]["at_risk"]
    assert k["stock_outs"] == plan["summary"]["by_status"].get("BACKORDERED", 0)
    assert k["service_level"]["target_pct"] == settings.service_level_target_pct
    assert k["service_level"]["met"] == (k["fill_rate_pct"] >= settings.service_level_target_pct)


def test_a_shortage_lowers_the_fill_rate_and_counts_as_a_stock_out(client):
    sku = free_sku(client)
    before = kpis(client, warehouse_id=WH)
    have = sku["stock_on_hand"]
    client.post(f"{API}/dispatch/orders", json={"orders": [order("K-ALL", sku, have), order("K-NONE", sku, 40, "Standard")]})
    after = kpis(client, warehouse_id=WH)
    assert after["orders"] == before["orders"] + 2
    assert after["units_ordered"] == before["units_ordered"] + have + 40
    assert after["units_planned"] == before["units_planned"] + have
    assert after["orders_fully_planned"] == before["orders_fully_planned"] + 1
    assert after["stock_outs"] == before["stock_outs"] + 1


def test_a_planner_lowering_a_quantity_lowers_the_fill_rate(client):
    line = next(l for l in current(client)["lines"] if l["qty_allocated"] >= 2 and l["status"] == "FULL")
    before = kpis(client)
    plan = current(client)
    client.patch(f"{API}/dispatch/plans/{plan['id']}/lines/{line['order_id']}",
                 json={"decision": "OVERRIDDEN", "override_qty": 1, "override_reason": "test"})
    after = kpis(client)
    assert after["units_planned"] == pytest.approx(before["units_planned"] - (line["qty_allocated"] - 1))


# ----------------------------------------------------------------- on time
def ship(client, oid):
    r = client.post(f"{API}/integrations/confirmations", json={"items": [{"order_id": oid, "status": "shipped"}]})
    assert r.status_code == 200 and r.json()["shipped"] == 1, r.text


def test_on_time_share_compares_the_shipment_with_the_due_date(client):
    assert kpis(client)["on_time_pct"] is None                 # nothing shipped yet
    sku = free_sku(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [
        order("K-EARLY", sku, 1), order("K-LATE", sku, 1, due="2026-02-02T10:00:00")]})
    plan = current(client)
    assert client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": WH}).status_code == 200
    ship(client, "K-EARLY")
    ship(client, "K-LATE")

    k = kpis(client, warehouse_id=WH)
    assert (k["shipped"], k["shipped_on_time"], k["on_time_pct"]) == (2, 1, 50.0)
    today = next(t for t in k["trend"] if t["date"] == date.today().isoformat())
    assert today["on_time_pct"] == 50.0 and today["shipped"] == 2
    assert today["fill_rate_pct"] is not None                  # approved today as well


def test_a_cancelled_order_is_not_a_shipment(client):
    sku = free_sku(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [order("K-GONE", sku, 1)]})
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": WH})
    client.post(f"{API}/integrations/confirmations", json={"items": [{"order_id": "K-GONE", "status": "cancelled"}]})
    assert kpis(client, warehouse_id=WH)["shipped"] == 0


def test_the_date_range_limits_shipments_and_plan_lines(client):
    sku = free_sku(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [order("K-DATED", sku, 1)]})
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": WH})
    ship(client, "K-DATED")

    async def backdate():
        async with AsyncSessionLocal() as db:
            row = await db.get(LedgerEntry, "K-DATED")
            row.closed_at = datetime(2026, 2, 5, 12, 0)
            await db.commit()
    asyncio.run(backdate())

    assert kpis(client, date_from="2026-02-05", date_to="2026-02-05")["shipped"] == 1
    assert kpis(client, date_from="2026-02-06")["shipped"] == 0
    assert kpis(client, date_to="2026-02-04")["shipped"] == 0
    far = (date.today() + timedelta(days=4000)).isoformat()
    assert kpis(client, date_from=far)["orders"] == 0
    assert client.get(f"{API}/kpis", params={"date_from": "2026-02-06", "date_to": "2026-02-05"}).status_code == 422


# ----------------------------------------------------------------- who may see what
def test_a_planner_sees_only_their_warehouse(client, anon):
    wh1 = kpis(client, warehouse_id="WH01")
    everyone = kpis(client)
    assert wh1["orders"] < everyone["orders"]

    sign_in(anon, "planner.wh01")
    mine = kpis(anon)
    assert mine["warehouse_id"] == "WH01" and mine["orders"] == wh1["orders"]
    assert anon.get(f"{API}/kpis", params={"warehouse_id": "WH02"}).status_code == 403


def test_a_viewer_may_read_and_a_stranger_may_not(anon):
    assert anon.get(f"{API}/kpis").status_code == 401
    sign_in(anon, "viewer")
    assert anon.get(f"{API}/kpis").status_code == 200
