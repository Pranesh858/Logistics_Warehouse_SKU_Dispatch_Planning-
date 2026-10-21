from app.modules.dispatch import packing
from app.modules.dispatch.wms import SimulatedWms, set_wms_client

API = "/api/v1"


def current(client):
    return client.get(f"{API}/dispatch/plans/current").json()


def trucks(client):
    return client.get(f"{API}/dispatch/trucks").json()


def small_trucks(client, capacity=40):
    """Make every warehouse's trucks small so the plan needs several of them."""
    for t in trucks(client):
        assert client.patch(f"{API}/dispatch/trucks/{t['id']}", json={"capacity_units": capacity}).status_code == 200


# ---------------------------------------------------------------- pure packing rules
def _item(oid, qty, tier="Standard", due=1, manual=None, wh="WH01"):
    return dict(order_id=oid, warehouse_id=wh, qty=qty, tier=tier, due_date=due, order_timestamp=due, manual_truck_id=manual)


def test_packing_priority_first_fit_and_unassigned():
    trucks_ = [dict(id=1, warehouse_id="WH01", capacity=10), dict(id=2, warehouse_id="WH01", capacity=10)]
    loads = packing.pack(trucks_, [_item("B", 8, "Basic"), _item("P", 8, "Premium"), _item("S", 8, "Standard")])
    by = {l["order_id"]: l["truck_id"] for l in loads}
    assert by == {"P": 1, "S": 2}               # Premium first, then Standard; Basic does not fit anywhere


def test_packing_splits_only_orders_bigger_than_every_truck():
    trucks_ = [dict(id=1, warehouse_id="WH01", capacity=10), dict(id=2, warehouse_id="WH01", capacity=10)]
    loads = packing.pack(trucks_, [_item("BIG", 15)])
    assert sorted((l["truck_id"], l["qty"]) for l in loads) == [(1, 10), (2, 5)]
    assert packing.pack(trucks_, [_item("OK", 9)])[0]["qty"] == 9      # fits one truck: kept whole


def test_packing_truck_only_serves_its_own_warehouse_and_honours_manual_choice():
    trucks_ = [dict(id=1, warehouse_id="WH01", capacity=10), dict(id=2, warehouse_id="WH01", capacity=10),
               dict(id=3, warehouse_id="WH02", capacity=10)]
    loads = packing.pack(trucks_, [_item("A", 5, manual=2), _item("B", 5, wh="WH02")])
    by = {l["order_id"]: (l["truck_id"], l["manual"]) for l in loads}
    assert by == {"A": (2, True), "B": (3, False)}


# ---------------------------------------------------------------- through the API
def test_default_trucks_exist_and_plan_has_truck_loads(client):
    assert len(trucks(client)) >= 6
    plan = current(client)
    assert plan["trucks"] and plan["summary"]["trucks_used"] >= 1
    sent_lines = [l for l in plan["lines"] if l["send_qty"] > 0]
    assert sent_lines and all(l["truck_assignments"] for l in sent_lines)
    cap = {t["id"]: t["capacity_units"] for t in plan["trucks"]}
    for t in plan["trucks"]:
        assert t["loaded_units"] <= cap[t["id"]] + 1e-6


def test_small_trucks_need_several_trucks_and_never_overload(client):
    small_trucks(client, 40)
    plan = current(client)
    used = [t for t in plan["trucks"] if t["loaded_units"] > 0]
    assert len(used) > 1
    for t in plan["trucks"]:
        assert t["loaded_units"] <= t["capacity_units"] + 1e-6
        assert t["fill_pct"] <= 100
    # a truck only carries its own warehouse's orders
    wh = {l["order_id"]: l["warehouse_id"] for l in plan["lines"]}
    for t in plan["trucks"]:
        assert all(wh[o["order_id"]] == t["warehouse_id"] for o in t["orders"])


def test_changing_truck_size_reloads_the_plan(client):
    before = current(client)["summary"]["trucks_used"]
    small_trucks(client, 25)
    assert current(client)["summary"]["trucks_used"] > before


def test_new_truck_takes_unassigned_orders(client):
    small_trucks(client, 20)
    plan = current(client)
    if not plan["unassigned"]:
        # shrink further until the trucks cannot hold everything
        small_trucks(client, 5)
        plan = current(client)
    assert plan["unassigned"], "expected some orders without a truck"
    wh = plan["unassigned"][0]["warehouse_id"]
    r = client.post(f"{API}/dispatch/trucks", json={"name": "Extra big", "warehouse_id": wh, "capacity_units": 100000})
    assert r.status_code == 201
    after = current(client)
    assert not [u for u in after["unassigned"] if u["warehouse_id"] == wh]


def test_truck_validation_and_remove(client):
    assert client.post(f"{API}/dispatch/trucks", json={"name": "X", "warehouse_id": "NOPE", "capacity_units": 10}).status_code == 422
    assert client.post(f"{API}/dispatch/trucks", json={"name": "X", "warehouse_id": "WH01", "capacity_units": 0}).status_code == 422
    first = trucks(client)[0]
    assert client.post(f"{API}/dispatch/trucks", json={"name": first["name"], "warehouse_id": first["warehouse_id"], "capacity_units": 5}).status_code == 409
    assert client.delete(f"{API}/dispatch/trucks/{first['id']}").status_code == 200
    assert first["id"] not in [t["id"] for t in trucks(client)]
    assert first["id"] not in [t["id"] for t in current(client)["trucks"]]
    assert client.patch(f"{API}/dispatch/trucks/99999", json={"capacity_units": 5}).status_code == 404


def test_planner_can_move_an_order_to_another_truck(client):
    plan = current(client)
    line = next(l for l in plan["lines"] if l["send_qty"] > 0)
    here = line["truck_assignments"][0]["truck_id"]
    other = next(t for t in plan["trucks"] if t["warehouse_id"] == line["warehouse_id"] and t["id"] != here)
    url = f"{API}/dispatch/plans/{plan['id']}/lines/{line['order_id']}/truck"
    r = client.patch(url, json={"truck_id": other["id"]})
    assert r.status_code == 200
    moved = next(l for l in r.json()["lines"] if l["order_id"] == line["order_id"])
    assert moved["truck_assignments"][0]["truck_id"] == other["id"] and moved["truck_assignments"][0]["manual"]
    # wrong warehouse is refused
    foreign = next(t for t in plan["trucks"] if t["warehouse_id"] != line["warehouse_id"])
    assert client.patch(url, json={"truck_id": foreign["id"]}).status_code == 422
    # hand it back to the system
    assert client.patch(url, json={"truck_id": None}).status_code == 200
    # the manual choice survives a rebuild
    client.patch(url, json={"truck_id": other["id"]})
    again = client.post(f"{API}/dispatch/plans/recalculate").json()
    kept = next(l for l in again["lines"] if l["order_id"] == line["order_id"])
    assert kept["truck_assignments"][0]["truck_id"] == other["id"]


def test_override_changes_truck_load(client):
    plan = current(client)
    line = next(l for l in plan["lines"] if l["send_qty"] > 1)
    r = client.patch(f"{API}/dispatch/plans/{plan['id']}/lines/{line['order_id']}",
                     json={"decision": "OVERRIDDEN", "override_qty": 1, "override_reason": "customer asked for 1"})
    got = next(l for l in r.json()["lines"] if l["order_id"] == line["order_id"])
    assert got["send_qty"] == 1 and sum(a["qty"] for a in got["truck_assignments"]) == 1


def test_only_loaded_units_are_sent_and_wms_gets_the_truck(client):
    sent_payloads = []

    class Spy(SimulatedWms):
        async def send(self, payload, attempt):
            sent_payloads.append(payload)
            return await super().send(payload, attempt)

    set_wms_client(Spy(failure_rate=0.0))
    small_trucks(client, 20)
    plan = current(client)
    unassigned = {u["order_id"] for u in plan["unassigned"]}
    loaded_units = plan["summary"]["units_to_send"]
    done = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={"approved_by": "p"}).json()
    assert sum(l["final_qty"] for l in done["lines"]) == loaded_units          # ledger = what was on trucks
    assert sent_payloads and all(p["trucks"] for p in sent_payloads)
    for p in sent_payloads:
        assert abs(sum(t["qty"] for t in p["trucks"]) - p["qty"]) < 1e-6
    sent_ids = {p["order_id"] for p in sent_payloads}
    assert not (sent_ids & {o for o in unassigned if next(l for l in plan["lines"] if l["order_id"] == o)["send_qty"] == 0})
    assert done["trucks"] and all(t["loaded_units"] <= t["capacity_units"] + 1e-6 for t in done["trucks"])
    set_wms_client(SimulatedWms(failure_rate=0.0))
