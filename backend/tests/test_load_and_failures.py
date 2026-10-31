"""Load and failure tests over real HTTP: many orders, a WMS that fails partway or hangs, and duplicate webhooks.

Each test states what must stay true when things go wrong: no order is booked twice, no stock moves twice, the
plan says honestly what did not reach the WMS, and nothing answers with a server error. Findings and timings are
written up in docs/LOAD_AND_FAILURE_REPORT.md; scripts/load_test.py runs the larger sizes.
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.models import StockLevel
from app.modules.stock.models import StockMovement
from tests.live import API, WEBHOOK_KEY, live, live_factory  # noqa: F401  (fixtures)

HOOKS = f"{API}/integrations/webhooks"


def make_orders(live, n, prefix="LOAD"):
    skus = live.get("/forecast/skus")
    now = datetime.now().replace(microsecond=0)
    tiers = ("Premium", "Standard", "Basic")
    return [{"order_id": f"{prefix}-{i:05d}", "order_timestamp": now.isoformat(), "customer_id": f"C{i % 500}",
             "customer_tier": tiers[i % 3], "product_id": skus[i % len(skus)]["product_id"],
             "warehouse_id": skus[i % len(skus)]["warehouse_id"], "qty_ordered": 1 + i % 4,
             "due_date": (now + timedelta(days=2 + i % 3)).isoformat()} for i in range(n)]


def ledger_sums_match(live):
    """Stock on hand minus what its movements add up to, for every SKU x warehouse where they differ."""
    async def go():
        async with AsyncSessionLocal() as db:
            levels = {(r.product_id, r.warehouse_id): r.qty for r in (await db.execute(select(StockLevel))).scalars()}
            sums: dict = {}
            for m in (await db.execute(select(StockMovement))).scalars():
                sums[(m.product_id, m.warehouse_id)] = sums.get((m.product_id, m.warehouse_id), 0.0) + m.qty
        return {k: (q, sums.get(k, 0.0)) for k, q in levels.items() if abs(q - sums.get(k, 0.0)) > 1e-6}

    return asyncio.run(go())


def shipment_count():
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(func.count()).select_from(StockMovement)
                                     .where(StockMovement.kind == "SHIPMENT"))).scalar_one()

    return asyncio.run(go())


def approve(live, warehouse_id=None):
    plan = live.get("/dispatch/plans/current")
    body = {"warehouse_id": warehouse_id} if warehouse_id else {}
    started = time.perf_counter()
    r = live.app.post(f"{API}/dispatch/plans/{plan['id']}/approve", json=body)
    return plan["id"], r, time.perf_counter() - started


def exports(live, plan_id):
    return live.get(f"/dispatch/plans/{plan_id}/exports")


# ----------------------------------------------------------------- load
def test_a_thousand_orders_go_through_end_to_end(live):
    orders = make_orders(live, 1000)
    t0 = time.perf_counter()
    live.post("/dispatch/orders", json={"orders": orders})
    ingest = time.perf_counter() - t0
    plan = live.get("/dispatch/plans/current")
    assert {o["order_id"] for o in orders} <= {ln["order_id"] for ln in plan["lines"]}

    plan_id, r, took = approve(live)
    assert r.status_code == 200, r.text
    sent = [x for x in exports(live, plan_id) if x["export_status"] == "SUCCESS"]
    assert sent and len(sent) == len(live.state["dispatch"])
    assert not any(o.get("duplicates") for o in live.state["dispatch"].values())

    t1 = time.perf_counter()
    out = live.fake.post("/control/wms/ship", json={}).json()
    shipped = time.perf_counter() - t1
    assert out["confirmations"]["status"] == 200 and out["confirmations"]["body"]["shipped"] == len(sent)
    assert live.get("/integrations/confirmations/pending")["count"] == 0
    assert shipment_count() == len(sent)
    assert ledger_sums_match(live) == {}
    print(f"\n1000 orders: ingest+plan {ingest:.1f}s, approve+export {len(sent)} {took:.1f}s, ship+confirm {shipped:.1f}s")
    assert ingest < 120 and took < 300 and shipped < 120


# ----------------------------------------------------------------- the WMS fails during approval
def test_the_wms_going_down_partway_leaves_an_honest_plan_and_a_clean_retry(live):
    live.fake.post("/control/wms/faults", json={"fail_after": 5})
    plan_id, r, _ = approve(live)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PARTIALLY_EXPORTED"
    log = exports(live, plan_id)
    assert len([x for x in log if x["export_status"] == "SUCCESS"]) == 5 == len(live.state["dispatch"])
    failed = [x for x in log if x["export_status"] == "FAILED"]
    assert failed and "503" in failed[0]["error"]
    # after a few failures in a row the export stops calling a WMS that is down and leaves the rest for a retry
    assert all("503" in x["error"] or x["error"].startswith("not tried") for x in failed)

    live.post("/alerts/sweep")
    assert any(a["kind"] == "export_failed" for a in live.get("/alerts"))

    live.fake.post("/control/wms/faults", json={})
    again = live.post(f"/dispatch/plans/{plan_id}/exports/retry")
    assert again["status"] == "EXPORTED"
    assert len(live.state["dispatch"]) == 5 + len(failed)
    assert not any(o.get("duplicates") for o in live.state["dispatch"].values()), "an order was sent twice"
    assert live.get("/integrations/confirmations/pending")["count"] == len(live.state["dispatch"])


def test_a_hanging_wms_cannot_hold_an_approval_for_long(live, monkeypatch):
    monkeypatch.setattr(settings, "wms_timeout_seconds", 1.0)
    live.fake.post("/control/wms/faults", json={"delay": 3})
    plan_id, r, took = approve(live)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PARTIALLY_EXPORTED"
    assert took < 30, f"approval took {took:.0f}s against a WMS that does not answer"
    errors = {x["error"] for x in exports(live, plan_id) if x["export_status"] == "FAILED"}
    assert errors and any("not tried" in e for e in errors)          # the rest were left for a retry, not hammered


def test_a_lost_reply_is_not_booked_twice(live):
    live.fake.post("/control/wms/faults", json={"lose_reply": True})
    plan_id, r, _ = approve(live, "WH01")
    assert r.status_code == 200, r.text
    booked = live.state["dispatch"]
    assert booked and all(o["warehouse_id"] == "WH01" for o in booked.values())
    pending = live.get("/integrations/confirmations/pending")["orders"]
    assert len(pending) == len({p["order_id"] for p in pending}) == len(booked)    # one hold per order


# ----------------------------------------------------------------- duplicate webhooks
def post_hook(live, path, body):
    return live.app.post(f"{HOOKS}/{path}", json=body, headers={"X-Integration-Key": WEBHOOK_KEY})


def at_once(n, fn):
    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(lambda _: fn(), range(n)))


def test_a_shipping_confirmation_sent_twice_ships_once(live):
    plan_id, _, _ = approve(live, "WH01")
    oid, sent = next((o, x) for o, x in live.state["dispatch"].items())
    pid = int(sent["product_id"])
    before = live.stock(pid, "WH01")
    body = {"items": [{"order_id": oid, "status": "shipped"}]}
    first, second = post_hook(live, "dispatch-confirmations", body), post_hook(live, "dispatch-confirmations", body)
    assert first.json()["shipped"] == 1 and second.json()["skipped"] == 1
    assert live.stock(pid, "WH01") == pytest.approx(before - sent["qty"])


def test_the_same_confirmation_arriving_at_once_ships_once(live):
    approve(live, "WH01")
    oid, sent = next((o, x) for o, x in live.state["dispatch"].items())
    pid = int(sent["product_id"])
    before = live.stock(pid, "WH01")
    body = {"items": [{"order_id": oid, "status": "shipped"}]}
    answers = at_once(8, lambda: post_hook(live, "dispatch-confirmations", body))
    assert all(a.status_code == 200 for a in answers), [a.text for a in answers if a.status_code != 200]
    assert sum(a.json()["shipped"] for a in answers) == 1
    assert live.stock(pid, "WH01") == pytest.approx(before - sent["qty"])
    ships = live.get("/stock/movements", params={"product_id": pid, "warehouse_id": "WH01", "kind": "SHIPMENT"})
    assert len(ships) == 1


def test_the_same_order_pushed_at_once_is_added_once(live):
    order = make_orders(live, 1, prefix="DUP")
    answers = at_once(8, lambda: post_hook(live, "orders", {"orders": order}))
    assert all(a.status_code == 200 for a in answers), [a.text for a in answers if a.status_code != 200]
    assert sum(a.json()["added"] for a in answers) == 1
    lines = [ln for ln in live.get("/dispatch/plans/current")["lines"] if ln["order_id"] == "DUP-00000"]
    assert len(lines) == 1


def test_the_same_stock_count_pushed_at_once_counts_once(live):
    sku = live.get("/forecast/skus")[0]
    pid, wh, before = sku["product_id"], sku["warehouse_id"], sku["stock_on_hand"]
    body = {"items": [{"product_id": pid, "warehouse_id": wh, "stock_on_hand": before + 50}]}
    answers = at_once(8, lambda: post_hook(live, "inventory", body))
    assert all(a.status_code == 200 for a in answers), [a.text for a in answers if a.status_code != 200]
    assert live.stock(pid, wh) == before + 50
    adj = live.get("/stock/movements", params={"product_id": pid, "warehouse_id": wh, "kind": "ADJUSTMENT"})
    assert [m["qty"] for m in adj] == [50]
