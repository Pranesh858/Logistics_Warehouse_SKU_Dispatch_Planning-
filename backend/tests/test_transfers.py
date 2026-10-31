"""Cross-warehouse transfers.

The rules that matter are the ones that stop a transfer doing harm: it must come out of stock the donor can
genuinely spare, it must arrive before the order it is meant to serve, and approving one must move the stock
so the same units cannot be promised twice.
"""
import pandas as pd
import pytest

from app.modules.dispatch import engine
from tests.conftest import sign_in

NOW = pd.Timestamp("2025-06-01 08:00")


def order(oid, pid, wh, qty, tier="Premium", due_days=5):
    return {"order_id": oid, "order_timestamp": NOW, "customer_id": f"C{oid}", "customer_tier": tier,
            "product_id": pid, "warehouse_id": wh, "qty_ordered": float(qty),
            "due_date": NOW + pd.Timedelta(days=due_days)}


def stock_frame(rows):
    return pd.DataFrame([{"product_id": p, "warehouse_id": w, "city": "X", "stock_on_hand": float(s)}
                         for p, w, s in rows])


def plan_for(orders, stock):
    return engine.allocate(pd.DataFrame(orders), stock, now=NOW)


# ----------------------------------------------------------------- the basic case
def test_spare_stock_elsewhere_becomes_a_proposal():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 20), (1, "WH05", 500)])
    plan = plan_for(orders, stock)
    assert plan.iloc[0]["qty_short"] == 80

    out = engine.propose_transfers(plan, stock, now=NOW, keep_days=0)
    assert len(out) == 1
    row = out.iloc[0]
    assert (row["product_id"], row["from_warehouse_id"], row["to_warehouse_id"]) == (1, "WH05", "WH01")
    assert row["qty"] == 80                      # the shortage, not everything WH05 has
    assert row["short_orders"] == 1


def test_no_proposal_when_nobody_else_holds_the_sku():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 20)])
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0)
    assert out.empty


def test_no_proposal_when_nothing_is_short():
    orders = [order("A1", 1, "WH01", 10)]
    stock = stock_frame([(1, "WH01", 500), (1, "WH05", 500)])
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0)
    assert out.empty


# ----------------------------------------------------------------- the donor is protected
def test_the_donor_keeps_a_buffer_of_its_own_demand():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 100)])
    demand = {(1, "WH05"): 10.0}                 # 10 a day at WH05

    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW,
                                   daily_demand=demand, keep_days=7)
    assert out.iloc[0]["qty"] == 30              # 100 on the shelf less 7 days x 10 kept back

    none = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW,
                                    daily_demand=demand, keep_days=10)
    assert none.empty                            # 10 days of cover leaves nothing to give


def test_the_donors_own_allocations_are_not_offered():
    """WH05's stock is already promised to its own orders, so it has nothing spare."""
    orders = [order("A1", 1, "WH01", 100), order("B1", 1, "WH05", 95)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 100)])
    plan = plan_for(orders, stock)
    assert plan[plan["order_id"] == "B1"].iloc[0]["qty_allocated"] == 95

    out = engine.propose_transfers(plan, stock, now=NOW, keep_days=0, min_units=1)
    assert out.iloc[0]["qty"] == 5               # only the 5 units nobody has claimed


def test_stock_the_ledger_holds_is_not_offered():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 100)])
    committed = {(1, "WH05"): 100.0}             # all of it reserved against an approved order
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW,
                                   committed=committed, keep_days=0)
    assert out.empty


def test_a_blocked_sku_is_neither_donor_nor_destination():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 500)])
    plan = plan_for(orders, stock)
    assert engine.propose_transfers(plan, stock, now=NOW, keep_days=0,
                                    blocked={(1, "WH05")}).empty
    blocked_dest = engine.allocate(pd.DataFrame(orders), stock, now=NOW, blocked={(1, "WH01")})
    assert engine.propose_transfers(blocked_dest, stock, now=NOW, keep_days=0,
                                    blocked={(1, "WH01")}).empty


# ----------------------------------------------------------------- transit time
def test_a_transfer_that_would_arrive_late_is_not_proposed():
    orders = [order("A1", 1, "WH01", 100, due_days=2)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 500)])
    plan = plan_for(orders, stock)
    assert len(engine.propose_transfers(plan, stock, now=NOW, keep_days=0, default_days=2)) == 1
    assert engine.propose_transfers(plan, stock, now=NOW, keep_days=0, default_days=3).empty


def test_only_the_orders_the_goods_can_still_reach_are_counted():
    orders = [order("A1", 1, "WH01", 50, due_days=1), order("A2", 1, "WH01", 50, due_days=9)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH05", 500)])
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0, default_days=4)
    assert len(out) == 1
    assert out.iloc[0]["qty"] == 50              # the order due tomorrow is beyond saving
    assert out.iloc[0]["short_orders"] == 1


def test_the_nearest_donor_is_asked_first():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH02", 60), (1, "WH05", 900)])
    lanes = {("WH05", "WH01"): 1, ("WH02", "WH01"): 4}
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0, lanes=lanes)
    assert len(out) == 1
    assert out.iloc[0]["from_warehouse_id"] == "WH05"


def test_a_shortage_is_split_across_donors_when_one_cannot_cover_it():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH02", 60), (1, "WH05", 30)])
    lanes = {("WH02", "WH01"): 1, ("WH05", "WH01"): 2}
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0, lanes=lanes)
    assert sorted(out["from_warehouse_id"]) == ["WH02", "WH05"]
    assert out["qty"].sum() == 90                # everything available; 10 still short


# ----------------------------------------------------------------- housekeeping
def test_tiny_proposals_are_dropped():
    orders = [order("A1", 1, "WH01", 52)]
    stock = stock_frame([(1, "WH01", 50), (1, "WH05", 500)])
    assert engine.propose_transfers(plan_for(orders, stock), stock, now=NOW,
                                    keep_days=0, min_units=5).empty
    assert len(engine.propose_transfers(plan_for(orders, stock), stock, now=NOW,
                                        keep_days=0, min_units=1)) == 1


def test_stock_already_on_its_way_is_not_sent_twice():
    orders = [order("A1", 1, "WH01", 100)]
    stock = stock_frame([(1, "WH01", 20), (1, "WH05", 500)])
    plan = plan_for(orders, stock)
    assert engine.propose_transfers(plan, stock, now=NOW, keep_days=0,
                                    incoming={(1, "WH01"): 80.0}).empty
    part = engine.propose_transfers(plan, stock, now=NOW, keep_days=0,
                                    incoming={(1, "WH01"): 50.0})
    assert part.iloc[0]["qty"] == 30


def test_a_donor_cannot_give_the_same_units_to_two_warehouses():
    orders = [order("A1", 1, "WH01", 100), order("B1", 1, "WH02", 100)]
    stock = stock_frame([(1, "WH01", 0), (1, "WH02", 0), (1, "WH05", 120)])
    out = engine.propose_transfers(plan_for(orders, stock), stock, now=NOW, keep_days=0)
    assert out["qty"].sum() == 120               # not 200
    assert len(out) == 2


def test_committed_lines_do_not_subtract_their_stock_twice():
    """A COMMITTED line's units are already held in the ledger; counting the line as well would understate
    the shelf and invent a shortage that is not there."""
    plan = pd.DataFrame([{
        "order_id": "A1", "order_timestamp": NOW, "product_id": 1, "warehouse_id": "WH01",
        "qty_allocated": 40.0, "qty_short": 0.0, "status": "COMMITTED",
        "due_date": NOW + pd.Timedelta(days=5),
    }])
    stock = stock_frame([(1, "WH01", 100)])
    assert engine.free_stock(plan, stock, {(1, "WH01"): 40.0}) == {(1, "WH01"): 60.0}


# ----------------------------------------------------------------- the API, end to end
#
# Note on the dataset: about 25 SKUs are stocked in two warehouses (scripts/make_multiwarehouse.py), and
# tests/test_multiwarehouse.py proves the engine raises a proposal from the real data. The rules above are
# proved on built frames; the tests below seed a transfer directly and prove the part that moves real stock.
API = "/api/v1"


def skus(client):
    r = client.get(f"{API}/forecast/skus")
    assert r.status_code == 200, r.text
    return r.json()


def stock_of(client, pid, wh):
    row = next((x for x in skus(client) if x["product_id"] == pid and x["warehouse_id"] == wh), None)
    return None if row is None else float(row["stock_on_hand"])


def stock_level(client, pid, wh):
    """Straight from the stock_levels table: the destination pair is not in the sales history."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.integrations.models import StockLevel

    async def go():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(StockLevel).where(
                StockLevel.product_id == pid, StockLevel.warehouse_id == wh))).scalars().all()
            return float(rows[0].qty) if rows else None

    return client.portal.call(go)


def seed_transfer(client, ref, pid, donor, dest, qty, transit_days=1):
    from app.core.database import AsyncSessionLocal
    from app.modules.dispatch.models import StockTransfer

    async def go():
        async with AsyncSessionLocal() as db:
            row = StockTransfer(transfer_ref=ref, product_id=pid, from_warehouse_id=donor,
                                to_warehouse_id=dest, qty=float(qty), transit_days=transit_days,
                                status="PROPOSED", reason="seeded by the test", short_orders=1)
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row.id

    return client.portal.call(go)


def a_route(client):
    """A SKU with plenty of stock, its own warehouse as donor, and some other warehouse as destination."""
    rows = sorted(skus(client), key=lambda x: -x["stock_on_hand"])
    donor_row = rows[0]
    others = sorted({x["warehouse_id"] for x in rows} - {donor_row["warehouse_id"]})
    if not others:
        pytest.skip("only one warehouse in this dataset")
    return donor_row["product_id"], donor_row["warehouse_id"], others[0]


def test_approving_takes_the_stock_off_the_donors_shelf(client):
    pid, donor, dest = a_route(client)
    before = stock_of(client, pid, donor)
    tid = seed_transfer(client, "TR-T1", pid, donor, dest, 40)

    r = client.post(f"{API}/dispatch/transfers/{tid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IN_TRANSIT"
    assert r.json()["eta"] is not None
    assert stock_of(client, pid, donor) == pytest.approx(before - 40, abs=0.01)
    assert stock_level(client, pid, dest) in (None, 0.0), \
        "the goods are in transit, not yet on the destination's shelf"


def test_receiving_puts_the_stock_on_the_destinations_shelf(client):
    pid, donor, dest = a_route(client)
    tid = seed_transfer(client, "TR-T2", pid, donor, dest, 25)
    client.post(f"{API}/dispatch/transfers/{tid}/approve")
    donor_after_send = stock_of(client, pid, donor)

    r = client.post(f"{API}/dispatch/transfers/{tid}/receive")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "RECEIVED"
    assert stock_level(client, pid, dest) == pytest.approx(25, abs=0.01)
    assert stock_of(client, pid, donor) == pytest.approx(donor_after_send, abs=0.01), \
        "arriving somewhere else must not change the donor again"


def test_cancelling_a_shipment_puts_the_stock_back(client):
    pid, donor, dest = a_route(client)
    before = stock_of(client, pid, donor)
    tid = seed_transfer(client, "TR-T3", pid, donor, dest, 30)
    client.post(f"{API}/dispatch/transfers/{tid}/approve")
    assert stock_of(client, pid, donor) == pytest.approx(before - 30, abs=0.01)

    r = client.post(f"{API}/dispatch/transfers/{tid}/cancel", json={"reason": "lorry broke down"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANCELLED"
    assert r.json()["cancel_reason"] == "lorry broke down"
    assert stock_of(client, pid, donor) == pytest.approx(before, abs=0.01)


def test_cancelling_a_proposal_moves_no_stock(client):
    pid, donor, dest = a_route(client)
    before = stock_of(client, pid, donor)
    tid = seed_transfer(client, "TR-T4", pid, donor, dest, 30)
    r = client.post(f"{API}/dispatch/transfers/{tid}/cancel", json={"reason": "not needed"})
    assert r.status_code == 200, r.text
    assert stock_of(client, pid, donor) == pytest.approx(before, abs=0.01)


def test_a_transfer_cannot_be_approved_twice(client):
    pid, donor, dest = a_route(client)
    tid = seed_transfer(client, "TR-T5", pid, donor, dest, 20)
    assert client.post(f"{API}/dispatch/transfers/{tid}/approve").status_code == 200
    again = client.post(f"{API}/dispatch/transfers/{tid}/approve")
    assert again.status_code == 422
    assert "in transit" in again.json()["detail"].lower()


def test_a_received_transfer_cannot_be_received_again(client):
    pid, donor, dest = a_route(client)
    tid = seed_transfer(client, "TR-T6", pid, donor, dest, 20)
    client.post(f"{API}/dispatch/transfers/{tid}/approve")
    assert client.post(f"{API}/dispatch/transfers/{tid}/receive").status_code == 200
    assert client.post(f"{API}/dispatch/transfers/{tid}/receive").status_code == 422


def test_more_than_the_donor_can_spare_is_refused(client):
    """The spare stock is checked again at approval, not trusted from when the proposal was raised."""
    pid, donor, dest = a_route(client)
    on_hand = stock_of(client, pid, donor)
    tid = seed_transfer(client, "TR-T7", pid, donor, dest, on_hand + 1000)
    r = client.post(f"{API}/dispatch/transfers/{tid}/approve")
    assert r.status_code == 422, r.text
    assert "can only spare" in r.json()["detail"]
    assert stock_of(client, pid, donor) == pytest.approx(on_hand, abs=0.01)


def test_the_summary_counts_what_is_outstanding(client):
    pid, donor, dest = a_route(client)
    seed_transfer(client, "TR-T8", pid, donor, dest, 15)
    r = client.get(f"{API}/dispatch/transfers/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["proposed"] >= 1
    assert body["proposed_units"] >= 15


def test_a_viewer_can_read_transfers_but_not_move_them(anon):
    sign_in(anon, "admin")
    pid, donor, dest = a_route(anon)
    tid = seed_transfer(anon, "TR-T9", pid, donor, dest, 15)

    r = anon.get(f"{API}/users")
    assert r.status_code == 200, r.text
    viewers = [u for u in r.json() if u["role"] == "viewer"]
    if not viewers:
        pytest.skip("no viewer account in this install")
    sign_in(anon, viewers[0]["username"])
    if anon.get(f"{API}/auth/me").status_code == 403:
        pytest.skip("this viewer must change their password first")
    assert anon.get(f"{API}/dispatch/transfers").status_code == 200
    assert anon.post(f"{API}/dispatch/transfers/{tid}/approve").status_code == 403


def test_a_planner_only_sees_transfers_touching_their_own_warehouse(anon):
    sign_in(anon, "admin")
    rows = sorted(skus(anon), key=lambda x: -x["stock_on_hand"])
    warehouses = sorted({x["warehouse_id"] for x in rows})
    if len(warehouses) < 3:
        pytest.skip("need three warehouses to prove the filter excludes anything")
    donor_row = rows[0]
    donor = donor_row["warehouse_id"]
    elsewhere = [w for w in warehouses if w != donor]
    seed_transfer(anon, "TR-TA", donor_row["product_id"], donor, elsewhere[0], 10)

    r = anon.get(f"{API}/users")
    planners = [u for u in r.json() if u["role"] == "planner" and u.get("warehouse_id")
                and u["warehouse_id"] not in (donor, elsewhere[0])]
    if not planners:
        pytest.skip("no planner scoped to an uninvolved warehouse")
    sign_in(anon, planners[0]["username"])
    if anon.get(f"{API}/auth/me").status_code == 403:
        pytest.skip("this planner must change their password first")
    mine = anon.get(f"{API}/dispatch/transfers").json()
    assert all(planners[0]["warehouse_id"] in (t["from_warehouse_id"], t["to_warehouse_id"]) for t in mine)
    assert not any(t["transfer_ref"] == "TR-TA" for t in mine)


def test_only_an_admin_sets_a_transit_lane(anon):
    sign_in(anon, "admin")
    r = anon.get(f"{API}/dispatch/transfer-lanes")
    assert r.status_code == 200, r.text
    assert r.json()["default_days"] >= 0

    whs = sorted({x["warehouse_id"] for x in skus(anon)})[:2]
    if len(whs) < 2:
        pytest.skip("need two warehouses")
    r = anon.put(f"{API}/dispatch/transfer-lanes",
                 json={"from_warehouse_id": whs[0], "to_warehouse_id": whs[1], "transit_days": 4})
    assert r.status_code == 200, r.text
    assert r.json()["transit_days"] == 4
    assert any(l["transit_days"] == 4 for l in anon.get(f"{API}/dispatch/transfer-lanes").json()["lanes"])

    same = anon.put(f"{API}/dispatch/transfer-lanes",
                    json={"from_warehouse_id": whs[0], "to_warehouse_id": whs[0], "transit_days": 1})
    assert same.status_code == 422
    unknown = anon.put(f"{API}/dispatch/transfer-lanes",
                       json={"from_warehouse_id": whs[0], "to_warehouse_id": "WH99", "transit_days": 1})
    assert unknown.status_code == 422

    assert anon.delete(f"{API}/dispatch/transfer-lanes/{whs[0]}/{whs[1]}").status_code == 204


def test_proposals_raised_together_never_share_a_reference(monkeypatch):
    """One rebuild can raise several proposals for the same warehouse in the same second. The reference must still
    be unique, or the database refuses the whole rebuild (seen once in a full run before this was fixed)."""
    from app.modules.dispatch import transfers

    monkeypatch.setattr(transfers.secrets, "token_hex", lambda n: "00" * n)    # the worst luck: no randomness at all
    refs = [transfers._ref("WH04", n) for n in range(50)]
    assert len(set(refs)) == len(refs) and max(map(len, refs)) <= 40
