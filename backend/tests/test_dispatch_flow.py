import pytest

from app.modules.dispatch.wms import SimulatedWms, set_wms_client

API = "/api/v1"


def current(client):
    r = client.get(f"{API}/dispatch/plans/current")
    assert r.status_code == 200
    return r.json()


def test_plan_is_recommended_automatically_and_nothing_is_sent(client):
    plan = current(client)
    assert plan["status"] == "RECOMMENDED"
    assert plan["trigger"] == "startup"
    assert plan["summary"]["orders"] > 0
    assert all(l["export_status"] is None for l in plan["lines"])
    assert client.get(f"{API}/dispatch/plans/{plan['id']}/exports").json() == []


def test_priority_and_no_over_allocation(client):
    plan = current(client)
    for l in plan["lines"]:
        assert l["qty_allocated"] <= l["qty_ordered"]
        if l["customer_tier"] == "Basic":
            assert l["qty_allocated"] in (0, l["qty_ordered"])          # held whole
    # tight stock: add orders far above stock, Premium must be served first
    sku = next(l for l in plan["lines"])
    pid, wh = sku["product_id"], sku["warehouse_id"]
    body = {"orders": [
        {"order_id": f"T{i}", "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C",
         "customer_tier": t, "product_id": pid, "warehouse_id": wh, "qty_ordered": 10_000_000,
         "due_date": "2026-02-02T10:00:00"} for i, t in enumerate(["Basic", "Standard", "Premium"])]}
    r = client.post(f"{API}/dispatch/orders", json=body)
    assert r.status_code == 200
    lines = {l["order_id"]: l for l in r.json()["lines"]}
    assert lines["T2"]["qty_allocated"] > 0 and lines["T1"]["qty_allocated"] == 0
    assert lines["T0"]["status"] == "HELD"
    stock = {(s["product_id"], s["warehouse_id"]): s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()}
    total = sum(l["qty_allocated"] for l in r.json()["lines"] if (l["product_id"], l["warehouse_id"]) == (pid, wh))
    assert total <= stock[(pid, wh)] + 1e-6


def test_approve_sends_to_wms_and_reserves_stock(client):
    plan = current(client)
    r = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "planner@example.com"})
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "EXPORTED"
    assert done["approved_by"] == "planner@example.com"
    sent = [l for l in done["lines"] if l["export_status"] == "SENT"]
    assert len(sent) == plan["summary"]["orders_to_send"] > 0
    log = client.get(f"{API}/dispatch/plans/{plan['id']}/exports").json()
    assert {x["export_status"] for x in log} == {"SUCCESS"}

    # the next recommendation carries approved orders forward untouched and cannot be approved twice
    nxt = current(client)
    assert nxt["id"] != plan["id"] and nxt["status"] == "RECOMMENDED"
    committed = {l["order_id"]: l for l in nxt["lines"] if l["status"] == "COMMITTED"}
    assert set(committed) == {l["order_id"] for l in sent}
    assert all(l["final_qty"] == 0 for l in committed.values())
    assert client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "x"}).status_code == 409


def test_no_double_allocation_after_new_orders(client):
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"})
    sent = {}
    for l in client.get(f"{API}/dispatch/plans/{plan['id']}").json()["lines"]:
        if l["export_status"] == "SENT":
            sent[(l["product_id"], l["warehouse_id"])] = sent.get((l["product_id"], l["warehouse_id"]), 0) + l["final_qty"]
    stock = {(s["product_id"], s["warehouse_id"]): s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()}
    key = next(iter(sent))
    r = client.post(f"{API}/dispatch/orders", json={"orders": [{
        "order_id": "NEW1", "order_timestamp": "2026-03-01T09:00:00", "customer_id": "C", "customer_tier": "Premium",
        "product_id": key[0], "warehouse_id": key[1], "qty_ordered": 10_000_000, "due_date": "2026-03-01T12:00:00"}]})
    new = next(l for l in r.json()["lines"] if l["order_id"] == "NEW1")
    assert new["qty_allocated"] <= stock[key] - sent[key] + 1e-6


def test_override_needs_reason_and_cannot_exceed_stock(client):
    plan = current(client)
    line = next(l for l in plan["lines"] if l["status"] == "PARTIAL" or l["qty_allocated"] > 0)
    url = f"{API}/dispatch/plans/{plan['id']}/lines/{line['order_id']}"
    assert client.patch(url, json={"decision": "OVERRIDDEN", "override_qty": 1}).status_code == 422
    assert client.patch(url, json={"decision": "OVERRIDDEN", "override_qty": 1, "override_reason": " "}).status_code == 422
    ok = client.patch(url, json={"decision": "OVERRIDDEN", "override_qty": 1, "override_reason": "customer asked for 1"})
    assert ok.status_code == 200
    got = next(l for l in ok.json()["lines"] if l["order_id"] == line["order_id"])
    assert got["final_qty"] == 1 and got["decision"] == "OVERRIDDEN"
    too_much = client.patch(url, json={"decision": "OVERRIDDEN", "override_qty": line["qty_ordered"] + 1, "override_reason": "x"})
    assert too_much.status_code == 422
    done = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"}).json()
    sent = next(l for l in done["lines"] if l["order_id"] == line["order_id"])
    assert sent["final_qty"] == 1 and sent["export_status"] == "SENT"


def test_rejected_line_is_not_sent(client):
    plan = current(client)
    line = next(l for l in plan["lines"] if l["qty_allocated"] > 0)
    client.patch(f"{API}/dispatch/plans/{plan['id']}/lines/{line['order_id']}", json={"decision": "REJECTED"})
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"})
    log = client.get(f"{API}/dispatch/plans/{plan['id']}/exports").json()
    assert line["order_id"] not in {x["order_id"] for x in log}


def test_failed_export_keeps_stock_reserved_and_can_be_retried(client):
    plan = current(client)
    victim = next(l for l in plan["lines"] if l["qty_allocated"] > 0)
    flaky = SimulatedWms(failure_rate=0.0, always_fail={victim["order_id"]})
    set_wms_client(flaky)
    done = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"}).json()
    assert done["status"] == "PARTIALLY_EXPORTED"
    assert done["summary"]["failed_exports"] == 1
    bad = next(l for l in done["lines"] if l["order_id"] == victim["order_id"])
    assert bad["export_status"] == "FAILED" and bad["export_error"]
    # stock stays reserved: the new recommendation shows it as committed, not re-allocatable
    nxt = current(client)
    assert next(l for l in nxt["lines"] if l["order_id"] == victim["order_id"])["status"] == "COMMITTED"
    set_wms_client(SimulatedWms(failure_rate=0.0))
    fixed = client.post(f"{API}/dispatch/plans/{plan['id']}/exports/retry").json()
    assert fixed["status"] == "EXPORTED"
    assert client.post(f"{API}/dispatch/plans/{plan['id']}/exports/retry").status_code == 409


def test_blocked_sku_is_never_allocated(client):
    plan = current(client)
    line = next(l for l in plan["lines"] if l["qty_allocated"] > 0)
    r = client.post(f"{API}/dispatch/blocked-skus", json={"product_id": line["product_id"],
                                                          "warehouse_id": line["warehouse_id"], "reason": "quality hold"})
    assert r.status_code == 200
    for l in r.json()["lines"]:
        if (l["product_id"], l["warehouse_id"]) == (line["product_id"], line["warehouse_id"]):
            assert l["status"] == "BLOCKED" and l["qty_allocated"] == 0


def test_invalid_orders_rejected(client):
    base = {"order_id": "BAD", "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C", "customer_tier": "Gold",
            "product_id": 999999, "warehouse_id": "WHX", "qty_ordered": 1, "due_date": "2026-02-02T10:00:00"}
    assert client.post(f"{API}/dispatch/orders", json={"orders": [base]}).status_code == 422


def test_outlook_links_plan_to_forecast(client):
    plan = current(client)
    rows = client.get(f"{API}/dispatch/plans/{plan['id']}/outlook").json()
    assert rows and {"stock_after_plan", "forecast_demand", "outlook"} <= set(rows[0])
    assert all(r["stock_after_plan"] >= -1e-6 for r in rows)
