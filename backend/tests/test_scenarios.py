"""POST /scenarios/run: what the adjustments do, and proof that a run leaves everything stored as it was."""
import asyncio

from sqlalchemy import func, select

from app.core.audit import AuditEntry
from app.core.database import AsyncSessionLocal
from app.integrations.models import StockLevel
from app.modules.dispatch.models import BlockedSku, ExportLog, LedgerEntry, Order, Plan, PlanChange, PlanLine, StockTransfer
from app.modules.stock.models import StockMovement
from tests.conftest import sign_in

API = "/api/v1"


def run(client, expect=200, **body):
    r = client.post(f"{API}/scenarios/run", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def current(client):
    return client.get(f"{API}/dispatch/plans/current").json()


def snapshot() -> dict:
    """Every row of everything a scenario must not touch."""
    async def read():
        async with AsyncSessionLocal() as db:
            out = {}
            for model in (Order, StockLevel, LedgerEntry, Plan, PlanLine, PlanChange, ExportLog, BlockedSku, StockTransfer, StockMovement):
                rows = (await db.execute(select(model))).scalars().all()
                out[model.__name__] = sorted(
                    (tuple(str(getattr(r, c.name)) for c in model.__table__.columns) for r in rows))
            return out
    return asyncio.run(read())


def audit_rows(action="scenario_run") -> int:
    async def read():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(func.count()).select_from(AuditEntry).where(AuditEntry.action == action))).scalar_one()
    return asyncio.run(read())


# ----------------------------------------------------------------- read-only
def test_a_scenario_changes_nothing_but_one_audit_entry(client):
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"warehouse_id": "WH01"})   # so the ledger has rows
    sku = current(client)["lines"][0]
    before = snapshot()
    audits = audit_rows()
    assert before["LedgerEntry"] and before["StockLevel"] and before["Order"]

    out = run(client,
              demand=[{"category": sku.get("category") or "Grocery", "multiplier": 3}, {"product_id": sku["product_id"], "multiplier": 5}],
              stock=[{"warehouse_id": "WH02", "change_pct": -60}],
              block=[{"product_id": sku["product_id"]}])
    assert out["after"] != out["before"]                       # it did simulate something

    assert snapshot() == before
    assert audit_rows() == audits + 1


def test_it_counts_the_orders_a_change_can_act_on(client):
    """At WH01 in the demo every order was already sent, and -70% stock read as a table of "no change"."""
    def still_open():
        return sum(1 for l in current(client)["lines"] if l["status"] != "COMMITTED")
    assert run(client)["open_orders"] == still_open() > 0
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={})
    assert run(client)["open_orders"] == still_open() < plan["summary"]["orders"]


def test_no_adjustments_means_no_difference(client):
    out = run(client)
    assert out["after"] == out["before"]
    assert all(v == 0 for v in out["difference"].values())
    assert out["plan_version"] == current(client)["version"]


# ----------------------------------------------------------------- what the adjustments do
def test_less_stock_lowers_the_fill_rate(client):
    out = run(client, warehouse_id="WH01", stock=[{"warehouse_id": "WH01", "change_pct": -100}])
    assert out["after"]["units_planned"] == 0
    assert out["after"]["backordered"] + out["after"]["held"] == out["after"]["orders"]
    assert out["difference"]["fill_rate_pct"] == -out["before"]["fill_rate_pct"]


def test_more_demand_raises_what_is_ordered_for_that_sku_only(client):
    line = current(client)["lines"][0]
    pid = line["product_id"]
    ordered = sum(l["qty_ordered"] for l in current(client)["lines"] if l["product_id"] == pid)
    out = run(client, demand=[{"product_id": pid, "multiplier": 2}])
    assert out["difference"]["units_ordered"] == round(ordered, 2)


def test_a_sku_multiplier_wins_over_its_category(client):
    from app.modules.forecast.runtime import runtime
    line = current(client)["lines"][0]
    pid = line["product_id"]
    category = runtime.sku_info().set_index("product_id").loc[pid, "category"]
    only_sku = run(client, demand=[{"product_id": pid, "multiplier": 2}])
    both = run(client, demand=[{"category": category, "multiplier": 1}, {"product_id": pid, "multiplier": 2}])
    assert both["after"]["units_ordered"] == only_sku["after"]["units_ordered"]
    wider = run(client, demand=[{"category": category, "multiplier": 2}])
    assert wider["after"]["units_ordered"] >= only_sku["after"]["units_ordered"]


def test_blocking_a_sku_stops_it_at_one_warehouse_or_all(client):
    line = current(client)["lines"][0]
    pid, wh = line["product_id"], line["warehouse_id"]
    lines = [l for l in current(client)["lines"] if l["product_id"] == pid]
    here = sum(1 for l in lines if l["warehouse_id"] == wh)
    assert run(client, block=[{"product_id": pid, "warehouse_id": wh}])["after"]["blocked"] == here
    assert run(client, block=[{"product_id": pid}])["after"]["blocked"] == len(lines)


def test_orders_already_sent_are_not_rescaled(client):
    plan = current(client)
    client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={})
    now = current(client)
    sent = [l for l in now["lines"] if l["status"] == "COMMITTED"]
    assert sent
    out = run(client, demand=[{"product_id": sent[0]["product_id"], "multiplier": 3}])
    extra = sum(l["qty_ordered"] * 2 for l in now["lines"]
                if l["product_id"] == sent[0]["product_id"] and l["status"] != "COMMITTED")
    assert out["difference"]["units_ordered"] == round(extra, 2)


def test_a_stale_plan_is_called_out(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "auto_replan", False)
    s = client.get(f"{API}/forecast/skus").json()[0]
    client.post(f"{API}/integrations/stock", json={"items": [{"product_id": s["product_id"], "warehouse_id": s["warehouse_id"],
                                                              "stock_on_hand": s["stock_on_hand"] + 9}]})
    assert run(client)["plan_changes"] == ["stock count changed for 1 SKU"]


# ----------------------------------------------------------------- what is refused
def test_something_unknown_is_refused_rather_than_ignored(client):
    assert "99999" in run(client, 422, demand=[{"product_id": 99999, "multiplier": 2}])["detail"]
    assert "Nope" in run(client, 422, demand=[{"category": "Nope", "multiplier": 2}])["detail"]
    assert "WH99" in run(client, 422, stock=[{"warehouse_id": "WH99", "change_pct": 5}])["detail"]
    assert "99999" in run(client, 422, block=[{"product_id": 99999}])["detail"]


def test_inputs_out_of_range_are_refused(client):
    run(client, 422, demand=[{"product_id": 1, "multiplier": 0}])
    run(client, 422, demand=[{"multiplier": 2}])
    run(client, 422, demand=[{"product_id": 1, "category": "Grocery", "multiplier": 2}])
    run(client, 422, stock=[{"warehouse_id": "WH01", "change_pct": -101}])


# ----------------------------------------------------------------- who may run it
def test_a_viewer_may_not_run_a_scenario(anon):
    assert anon.post(f"{API}/scenarios/run", json={}).status_code == 401
    sign_in(anon, "viewer")
    assert anon.post(f"{API}/scenarios/run", json={}).status_code == 403


def test_a_planner_simulates_their_own_warehouse_only(client, anon):
    wh1 = run(client, warehouse_id="WH01")
    sign_in(anon, "planner.wh01")
    mine = run(anon)
    assert mine["warehouse_id"] == "WH01" and mine["before"]["orders"] == wh1["before"]["orders"]
    run(anon, 403, warehouse_id="WH02")
    run(anon, 403, stock=[{"warehouse_id": "WH02", "change_pct": 5}])
    run(anon, 403, block=[{"product_id": 1, "warehouse_id": "WH02"}])
