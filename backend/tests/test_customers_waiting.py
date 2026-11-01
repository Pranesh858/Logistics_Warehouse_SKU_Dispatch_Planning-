"""Units to order counts customers who are already waiting, not only the forecast.

A Premium order for 150 of #38 at WH01 was planned 87 and short 63, yet Units to order said "Covered": the
forecast for the next ten days (87) matched the shelf (87), and the order already placed was not counted at all.
"""
import math

API = "/api/v1"


def needs(client, **params):
    r = client.get(f"{API}/forecast/orders", params={"days": 7, "safety": "true", "include_covered": "true", **params})
    assert r.status_code == 200, r.text
    return r.json()


def row_for(data, pid, wh):
    return next(r for r in data["rows"] if r["product_id"] == pid and r["warehouse_id"] == wh)


def short_order(client, short=40, tier="Premium"):
    """Stock set to just cover the forecast, then an order `short` units bigger than the shelf."""
    in_plan = {(l["product_id"], l["warehouse_id"]) for l in client.get(f"{API}/dispatch/plans/current").json()["lines"]}
    row = next(r for r in needs(client)["rows"] if (r["product_id"], r["warehouse_id"]) not in in_plan
               and r["forecast_high"] >= 5)
    pid, wh = row["product_id"], row["warehouse_id"]
    shelf = math.ceil(row["forecast_high"])
    client.post(f"{API}/integrations/stock", json={"items": [{"product_id": pid, "warehouse_id": wh, "stock_on_hand": shelf}]})
    assert row_for(needs(client), pid, wh)["units_to_order"] == 0          # the forecast alone is covered
    order = {"order_id": "WAIT-1", "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C-W", "customer_tier": tier,
             "product_id": pid, "warehouse_id": wh, "qty_ordered": shelf + short, "due_date": "2026-02-03T10:00:00"}
    plan = client.post(f"{API}/dispatch/orders", json={"orders": [order]}).json()
    line = next(l for l in plan["lines"] if l["order_id"] == "WAIT-1")
    assert line["qty_short"] == short
    return pid, wh, plan, line


def test_an_order_the_shelf_cannot_fill_is_on_the_ordering_list(client):
    pid, wh, _, _ = short_order(client, short=40)
    data = needs(client)
    row = row_for(data, pid, wh)
    assert row["waiting"] == 40
    assert row["units_to_order"] == 40 and row["priority"] == "Order now"
    assert data["rows"][0]["waiting"] > 0                                 # customers waiting come first
    assert data["summary"]["skus_with_customers_waiting"] >= 1


def test_send_to_erp_orders_it_and_then_it_is_covered(client):
    pid, wh, _, _ = short_order(client, short=40)
    pos = client.post(f"{API}/integrations/purchase-orders", json={"days": 7, "warehouse_id": wh, "urgent_only": True})
    assert pos.status_code == 200, pos.text
    line = next(l for l in pos.json()[0]["lines"] if l["product_id"] == pid)
    assert line["units"] == 40
    row = row_for(needs(client), pid, wh)
    assert row["on_order"] == 40 and row["units_to_order"] == 0           # not ordered twice


def test_a_rejected_order_is_not_waited_for(client):
    pid, wh, plan, line = short_order(client, short=40)
    r = client.patch(f"{API}/dispatch/plans/{plan['id']}/lines/WAIT-1",
                     json={"decision": "REJECTED", "override_reason": "customer cancelled by phone"})
    assert r.status_code == 200, r.text
    row = row_for(needs(client), pid, wh)
    assert row["waiting"] == 0 and row["units_to_order"] == 0


def test_the_stock_alert_says_customers_are_waiting(client):
    pid, wh, _, _ = short_order(client, short=40)
    assert client.post(f"{API}/alerts/sweep").status_code == 200
    mine = [a for a in client.get(f"{API}/alerts").json() if a["product_id"] == pid and a["warehouse_id"] == wh]
    assert mine and mine[0]["title"].startswith("Customers are waiting for 40 units")
