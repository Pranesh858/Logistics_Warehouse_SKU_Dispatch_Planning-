"""A warehouse takes orders only for the products it stocks, whichever way the order comes in.

The ERP feed already skipped an order for a product its warehouse does not carry; an order entered by hand was
accepted, sat out of stock, and could only ever be filled by a transfer days later.
"""
import pandas as pd
import pytest

from app.modules.dispatch import engine

API = "/api/v1"


def test_the_engine_names_each_product_a_warehouse_does_not_carry():
    orders = pd.DataFrame([
        {"order_id": "A", "product_id": 1, "warehouse_id": "WH01", "qty_ordered": 2, "customer_tier": "Standard"},
        {"order_id": "B", "product_id": 1, "warehouse_id": "WH03", "qty_ordered": 2, "customer_tier": "Standard"},
    ])
    known_p, known_w = {1}, {"WH01", "WH03"}
    engine.validate_orders(orders, known_p, known_w)                     # without a range: as before
    with pytest.raises(ValueError, match="WH01 does not stock product 1"):
        engine.validate_orders(orders, known_p, known_w, stocked={(1, "WH03")})
    engine.validate_orders(orders.iloc[[1]], known_p, known_w, stocked={(1, "WH03")})


def test_an_order_by_hand_for_a_product_the_warehouse_does_not_stock_is_refused(client):
    skus = client.get(f"{API}/forecast/skus").json()
    where = {}
    for s in skus:
        where.setdefault(s["product_id"], set()).add(s["warehouse_id"])
    pid, home = next((p, next(iter(w))) for p, w in where.items() if len(w) == 1)
    elsewhere = next(s["warehouse_id"] for s in skus if s["warehouse_id"] != home)

    def order(oid, wh):
        return {"orders": [{"order_id": oid, "order_timestamp": "2026-11-02T08:00:00", "customer_id": "C-R",
                            "customer_tier": "Standard", "product_id": pid, "warehouse_id": wh, "qty_ordered": 2,
                            "due_date": "2026-11-03T08:00:00"}]}

    r = client.post(f"{API}/dispatch/orders", json=order("RANGE-NO", elsewhere))
    assert r.status_code == 422
    assert f"{elsewhere} does not stock product {pid}" in r.json()["detail"]
    assert client.post(f"{API}/dispatch/orders", json=order("RANGE-YES", home)).status_code == 200
