"""What happens to the part of an order that was not sent when the rest of it was approved.

Two ways an order goes out only in part:
  * it is bigger than every truck of its warehouse, so it is split and only what fits is loaded;
  * there is not enough stock, so only some of it is allocated.
In both cases the units that were not sent should come back in a later plan, not be dropped.

KNOWN BUG, not fixed yet: once part of an order is committed the engine treats the whole order as done
(engine.allocate, "already_committed_carried_forward"), so the rest is never planned again. These tests are marked
xfail(strict=True): they fail today, and the suite will flag them as soon as a fix makes them pass.
"""
import pytest

KNOWN_BUG = pytest.mark.xfail(strict=True, reason="the unsent part of a partly dispatched order is dropped")
API = "/api/v1"
WH = "WH01"


def current(client):
    return client.get(f"{API}/dispatch/plans/current").json()


def line(plan, oid):
    return next((ln for ln in plan["lines"] if ln["order_id"] == oid), None)


def one_truck(client, capacity):
    """Leave WH01 with a single active truck of the given size."""
    mine = [t for t in client.get(f"{API}/dispatch/trucks").json() if t["warehouse_id"] == WH]
    for t in mine[1:]:
        assert client.patch(f"{API}/dispatch/trucks/{t['id']}", json={"active": False}).status_code == 200
    assert client.patch(f"{API}/dispatch/trucks/{mine[0]['id']}", json={"capacity_units": capacity}).status_code == 200


def all_trucks_big(client):
    for t in client.get(f"{API}/dispatch/trucks").json():
        assert client.patch(f"{API}/dispatch/trucks/{t['id']}", json={"capacity_units": 100000}).status_code == 200


def first_in_line_order(client, oid, product_id, qty):
    """A Premium order due long before any other, so it is first for both stock and truck space."""
    body = {"orders": [{"order_id": oid, "order_timestamp": "2020-01-01T00:00:00", "customer_id": "C-TEST",
                        "customer_tier": "Premium", "product_id": product_id, "warehouse_id": WH,
                        "qty_ordered": qty, "due_date": "2020-01-01T06:00:00"}]}
    r = client.post(f"{API}/dispatch/orders", json=body)
    assert r.status_code == 200, r.text


def approve(client):
    plan = current(client)
    r = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": WH})
    assert r.status_code == 200, r.text
    return {x["order_id"]: x for x in client.get(f"{API}/dispatch/plans/{plan['id']}/exports").json()}


def well_stocked_product(client):
    skus = [s for s in client.get(f"{API}/forecast/skus").json() if s["warehouse_id"] == WH]
    return max(skus, key=lambda s: s["stock_on_hand"])


def report(tag, ln, plan, oid):
    left = [u for u in plan["unassigned"] if u["order_id"] == oid]
    print(f"\n[{tag}] next plan: status={ln['status']} ordered={ln['qty_ordered']} allocated={ln['qty_allocated']} "
          f"short={ln['qty_short']} final={ln['final_qty']} send={ln['send_qty']} unassigned={left}")


@KNOWN_BUG
def test_leftover_of_an_order_split_across_trucks_comes_back(client):
    oid = "TEST-SPLIT"
    sku = well_stocked_product(client)
    one_truck(client, capacity=5)
    first_in_line_order(client, oid, sku["product_id"], qty=30)

    before = line(current(client), oid)
    assert before["final_qty"] == 30 and before["send_qty"] == 5          # only 5 fit on the one truck

    sent = approve(client)
    assert sent[oid]["qty"] == 5                                           # 5 went to the WMS

    after = current(client)
    ln = line(after, oid)
    report("split", ln, after, oid)
    left = sum(u["qty"] for u in after["unassigned"] if u["order_id"] == oid)
    # The other 25 must still be planned: on a truck now, or waiting for one.
    assert ln["send_qty"] + left == 25, "the 25 units that did not fit were dropped after approval"


@KNOWN_BUG
def test_stock_short_part_of_an_order_is_sent_once_stock_arrives(client):
    oid = "TEST-SHORT"
    all_trucks_big(client)
    sku = well_stocked_product(client)
    pid, have = sku["product_id"], sku["stock_on_hand"]
    first_in_line_order(client, oid, pid, qty=have + 50)

    before = line(current(client), oid)
    got = before["qty_allocated"]
    assert before["status"] == "PARTIAL" and before["qty_short"] >= 50

    sent = approve(client)
    assert sent[oid]["qty"] == got

    r = client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": pid, "warehouse_id": WH, "stock_on_hand": have + 500}], "reason": "delivery"})
    assert r.status_code == 200, r.text

    after = current(client)
    ln = line(after, oid)
    report("short", ln, after, oid)
    assert ln["final_qty"] - got > 0, "new stock arrived but the rest of the order was never planned again"
