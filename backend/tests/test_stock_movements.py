"""Stock lives in database tables, and every change to it is a recorded movement.

The rule that matters: for every SKU x warehouse, the sum of its movements (the OPENING figure included) is exactly
the stock on hand. If any code path changed stock without a movement, or wrote a movement without changing stock,
this would stop adding up.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.models import StockLevel
from app.modules.forecast.runtime import runtime
from app.modules.stock.models import StockMovement
from tests.conftest import sign_in

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from demo_run import Demo  # noqa: E402

API = "/api/v1"


def movements(client, **params):
    r = client.get(f"{API}/stock/movements", params={"limit": 1000, **params})
    assert r.status_code == 200, r.text
    return r.json()


def stock_of(client, pid, wh):
    return next((s["stock_on_hand"] for s in client.get(f"{API}/forecast/skus").json()
                 if s["product_id"] == pid and s["warehouse_id"] == wh), None)


def assert_ledger_adds_up(client):
    async def go():
        async with AsyncSessionLocal() as db:
            levels = {(r.product_id, r.warehouse_id): r.qty for r in (await db.execute(select(StockLevel))).scalars()}
            sums: dict = {}
            for m in (await db.execute(select(StockMovement))).scalars():
                sums[(m.product_id, m.warehouse_id)] = sums.get((m.product_id, m.warehouse_id), 0.0) + m.qty
            return levels, sums

    levels, sums = client.portal.call(go)
    wrong = {k: (q, sums.get(k, 0.0)) for k, q in levels.items() if abs(q - sums.get(k, 0.0)) > 1e-6}
    assert not wrong, f"stock that the movements do not explain: {list(wrong.items())[:5]}"


# ----------------------------------------------------------------- seeding
def test_master_data_and_opening_stock_come_from_the_seed_files(client):
    seed = pd.read_csv(settings.seed_stock_path)
    rows = client.get(f"{API}/forecast/skus").json()
    assert len(rows) == len(seed)
    got = {(r["product_id"], r["warehouse_id"]): r["stock_on_hand"] for r in rows}
    assert all(got[(r.product_id, r.warehouse_id)] == r.stock_on_hand for r in seed.itertuples())
    assert {r["category"] for r in rows} <= set(pd.read_csv(settings.seed_skus_path)["category"])

    opening = movements(client, kind="OPENING")
    assert len(opening) == len(seed)
    assert_ledger_adds_up(client)


def test_listing_stock_does_not_need_the_sales_history(client, monkeypatch):
    def no_csv(*_):
        raise AssertionError("the sales history CSV was read")

    monkeypatch.setattr(type(runtime), "_ensure", no_csv)
    rows = client.get(f"{API}/forecast/skus").json()
    assert rows and all(r["category"] and r["city"] for r in rows)


# ----------------------------------------------------------------- every way stock moves
def test_a_count_is_an_adjustment_with_who_and_why(client):
    sku = client.get(f"{API}/forecast/skus").json()[0]
    pid, wh, before = sku["product_id"], sku["warehouse_id"], sku["stock_on_hand"]
    r = client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": pid, "warehouse_id": wh, "stock_on_hand": before + 25}], "reason": "found a pallet"})
    assert r.json()["changed"] == 1

    m = movements(client, product_id=pid, warehouse_id=wh, kind="ADJUSTMENT")[0]
    assert (m["qty"], m["qty_after"], m["username"], m["reason"], m["source"]) == (25, before + 25, "admin",
                                                                                   "found a pallet", "manual")
    # the same count again changes nothing, so it is not a movement
    client.post(f"{API}/integrations/stock", json={"items": [{"product_id": pid, "warehouse_id": wh,
                                                              "stock_on_hand": before + 25}]})
    assert len(movements(client, product_id=pid, warehouse_id=wh, kind="ADJUSTMENT")) == 1
    assert_ledger_adds_up(client)


def test_the_whole_demo_story_leaves_a_matching_trail(anon):
    facts = Demo(anon, say=lambda *_: None).run()
    sign_in(anon, "admin")
    pid, ref = facts["product_id"], facts["transfer"]["transfer_ref"]

    out = movements(anon, product_id=pid, warehouse_id=facts["donor"], kind="TRANSFER_OUT")
    into = movements(anon, product_id=pid, warehouse_id=facts["dest"], kind="TRANSFER_IN")
    shipped = movements(anon, product_id=pid, warehouse_id=facts["dest"], kind="SHIPMENT")
    assert [m["ref"] for m in out] == [ref] and [m["ref"] for m in into] == [ref]
    assert out[0]["qty"] == -facts["transfer"]["qty"] and into[0]["qty"] == facts["transfer"]["qty"]
    assert [m["ref"] for m in shipped] == [facts["order_id"]]
    assert shipped[0]["qty"] == -facts["sent_qty"] and shipped[0]["qty_after"] == facts["final_stock"]
    assert_ledger_adds_up(anon)


def test_a_transfer_turned_back_returns_the_goods_on_the_ledger(client):
    from tests.test_transfers import a_route, seed_transfer

    pid, donor, dest = a_route(client)
    before = stock_of(client, pid, donor)
    tid = seed_transfer(client, "TR-RET", pid, donor, dest, 30)
    client.post(f"{API}/dispatch/transfers/{tid}/approve")
    client.post(f"{API}/dispatch/transfers/{tid}/cancel", json={"reason": "lorry broke down"})

    kinds = [m["kind"] for m in movements(client, product_id=pid, warehouse_id=donor)]
    assert kinds[:2] == ["TRANSFER_RETURN", "TRANSFER_OUT"]          # newest first
    back = movements(client, product_id=pid, warehouse_id=donor, kind="TRANSFER_RETURN")[0]
    assert back["reason"] == "lorry broke down" and back["ref"] == "TR-RET"
    assert stock_of(client, pid, donor) == pytest.approx(before)
    assert_ledger_adds_up(client)


def test_receiving_a_purchase_order_puts_the_goods_on_the_shelf(client):
    po = client.post(f"{API}/integrations/purchase-orders", json={"days": 7, "urgent_only": True}).json()[0]
    line = po["lines"][0]
    pid, wh = line["product_id"], po["warehouse_id"]
    before = stock_of(client, pid, wh)

    assert client.post(f"{API}/integrations/purchase-orders/{po['id']}/receive").status_code == 200
    got = movements(client, product_id=pid, warehouse_id=wh, kind="RECEIPT")
    assert [(m["qty"], m["ref"]) for m in got] == [(line["units"], po["po_ref"])]
    assert stock_of(client, pid, wh) == pytest.approx(before + line["units"])
    assert len(movements(client, kind="RECEIPT")) == len([ln for ln in po["lines"] if ln["units"] > 0])
    assert_ledger_adds_up(client)


# ----------------------------------------------------------------- access
def test_a_planner_sees_only_their_own_warehouse(anon):
    sign_in(anon, "planner.wh02")
    rows = movements(anon)
    assert rows and {m["warehouse_id"] for m in rows} == {"WH02"}
    assert anon.get(f"{API}/stock/movements", params={"warehouse_id": "WH01"}).status_code == 403


# ----------------------------------------------------------------- new data and older databases
def test_a_pair_new_in_the_sales_history_becomes_stocked(client, monkeypatch):
    """After a dataset upload: a SKU at a warehouse the tables do not know gets master data and opening stock."""
    from app.modules.stock import service as stock_service

    day = pd.Timestamp("2025-12-31")
    fake = pd.DataFrame([{"product_id": 9001, "warehouse_id": "WH07", "city": "Salem", "date": day,
                          "stock_on_hand": 120.0, "product_name": "Test Rice 1kg", "category": "Grocery",
                          "is_organic": False, "shelf_life_days": 180, "weight_g": 1000.0}])
    monkeypatch.setattr(runtime, "_frame", fake)

    async def go():
        async with AsyncSessionLocal() as db:
            first = await stock_service.register_from_history(db)
            again = await stock_service.register_from_history(db)
            return first, again

    assert client.portal.call(go) == (1, 0)
    row = next(r for r in client.get(f"{API}/forecast/skus").json() if r["product_id"] == 9001)
    assert (row["warehouse_id"], row["city"], row["category"], row["stock_on_hand"]) == ("WH07", "Salem", "Grocery", 120)
    assert movements(client, product_id=9001)[0]["kind"] == "OPENING"
    assert_ledger_adds_up(client)


def test_stock_from_before_the_ledger_gets_an_opening_movement(client):
    """A database from an older version has stock rows and no movements; the next start gives each a starting point."""
    from sqlalchemy import delete

    from app.modules.stock import service as stock_service

    sku = client.get(f"{API}/forecast/skus").json()[0]
    key = (sku["product_id"], sku["warehouse_id"])

    async def go():
        async with AsyncSessionLocal() as db:
            await db.execute(delete(StockMovement).where(StockMovement.product_id == key[0],
                                                         StockMovement.warehouse_id == key[1]))
            await db.commit()
            return await stock_service.seed(db)

    assert client.portal.call(go)["opening"] == 1
    assert [m["kind"] for m in movements(client, product_id=key[0], warehouse_id=key[1])] == ["OPENING"]
    assert_ledger_adds_up(client)
