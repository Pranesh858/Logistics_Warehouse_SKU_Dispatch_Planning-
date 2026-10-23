"""Ordering has to survive contact with a real supply chain: stock takes days to arrive, and what is
already on its way must not be ordered twice."""
import pytest

from app.core.config import settings
from app.modules.dispatch.wms import SimulatedWms, set_wms_client
from tests.conftest import sign_in

API = "/api/v1"


def needs(client, **params):
    q = "&".join(f"{k}={v}" for k, v in {"days": 7, "safety": "false", "include_covered": "true", **params}.items())
    r = client.get(f"{API}/forecast/orders?{q}")
    assert r.status_code == 200, r.text
    return r.json()


def row_for(data, pid, wh):
    return next((r for r in data["rows"] if r["product_id"] == pid and r["warehouse_id"] == wh), None)


def test_lead_time_lengthens_the_cover_period(client):
    base = needs(client)
    assert base["default_lead_time_days"] == settings.default_lead_time_days
    first = base["rows"][0]
    pid, wh = first["product_id"], first["warehouse_id"]
    assert first["cover_days"] == 7 + settings.default_lead_time_days
    assert first["lead_time_days"] == settings.default_lead_time_days

    # a slow supplier must be covered for longer, so more units are needed
    assert client.put(f"{API}/forecast/lead-times", json={"product_id": pid, "lead_time_days": 21,
                                                          "supplier": "Slow Mills"}).status_code == 200
    slow = row_for(needs(client), pid, wh)
    assert slow["lead_time_days"] == 21 and slow["cover_days"] == 28
    assert slow["forecast_units"] > first["forecast_units"]
    assert slow["units_to_order"] > first["units_to_order"]

    listed = client.get(f"{API}/forecast/lead-times").json()
    saved = next(x for x in listed["skus"] if x["product_id"] == pid)
    assert saved["lead_time_days"] == 21 and saved["supplier"] == "Slow Mills" and saved["updated_by"] == "admin"

    client.delete(f"{API}/forecast/lead-times/{pid}")
    assert row_for(needs(client), pid, wh)["lead_time_days"] == settings.default_lead_time_days


def test_lead_time_is_admin_only_and_checked(client, anon):
    assert client.put(f"{API}/forecast/lead-times", json={"product_id": 1, "lead_time_days": 99}).status_code == 422
    assert client.put(f"{API}/forecast/lead-times", json={"product_id": 999999, "lead_time_days": 5}).status_code == 422
    sign_in(anon, "planner.wh01")
    assert anon.put(f"{API}/forecast/lead-times", json={"product_id": 1, "lead_time_days": 5}).status_code == 403
    assert anon.get(f"{API}/forecast/lead-times").status_code == 200


def test_stock_already_on_order_is_not_ordered_again(client):
    before = needs(client, days=7)
    assert before["on_order_units"] == 0
    pos = client.post(f"{API}/integrations/purchase-orders", json={"days": 7, "safety": False, "urgent_only": True}).json()
    assert pos and all(p["status"] == "SENT" for p in pos)

    after = needs(client, days=7)
    assert after["on_order_units"] > 0
    ordered = {(l["product_id"], p["warehouse_id"]): l["units"] for p in pos for l in p["lines"]}
    pid, wh = next(iter(ordered))
    row = row_for(after, pid, wh)
    assert row["on_order"] == ordered[(pid, wh)]
    # the same units are not asked for twice
    assert after["summary"]["units_to_order"] < before["summary"]["units_to_order"]
    was = row_for(before, pid, wh)["units_to_order"]
    assert row["units_to_order"] == max(0, was - ordered[(pid, wh)])


def test_receiving_a_purchase_order_stops_it_counting_as_on_order(client, anon):
    po = client.post(f"{API}/integrations/purchase-orders", json={"days": 7, "urgent_only": True}).json()[0]
    assert needs(client)["on_order_units"] > 0

    got = client.post(f"{API}/integrations/purchase-orders/{po['id']}/receive")
    assert got.status_code == 200 and got.json()["received_at"] is not None
    assert client.post(f"{API}/integrations/purchase-orders/{po['id']}/receive").status_code == 422   # only once

    left = needs(client)["rows"]
    assert all(r["on_order"] == 0 for r in left if r["warehouse_id"] == po["warehouse_id"])

    sign_in(anon, "planner.wh02")
    other = anon.post(f"{API}/integrations/purchase-orders", json={"days": 7}).json()[0]
    assert client.post(f"{API}/integrations/purchase-orders/{other['id']}/receive").status_code == 200


def test_urgency_follows_the_delivery_wait(client):
    first = needs(client)["rows"][0]
    pid, wh = first["product_id"], first["warehouse_id"]
    client.put(f"{API}/forecast/lead-times", json={"product_id": pid, "lead_time_days": 20})
    row = row_for(needs(client), pid, wh)
    # 20 days to arrive: anything with less cover than that cannot wait
    if row["days_of_cover"] is not None and row["days_of_cover"] < 20:
        assert row["priority"] == "Order now"
