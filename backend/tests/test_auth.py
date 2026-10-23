from fastapi.testclient import TestClient

from tests.conftest import DEMO_PASSWORD, sign_in

API = "/api/v1"
D = f"{API}/dispatch"


def plan_of(c):
    r = c.get(f"{D}/plans/current")
    assert r.status_code == 200, r.text
    return r.json()


def other_warehouse_line(c, mine):
    return next(l for l in plan_of(c)["lines"] if l["warehouse_id"] != mine)


def as_user(anon, name):
    sign_in(anon, name)
    return anon


# ------------------------------------------------------------------ login
def test_everything_but_login_and_health_needs_a_sign_in(anon):
    assert anon.get("/health").status_code == 200
    for url in (f"{D}/plans/current", f"{D}/trucks", f"{API}/forecast/skus", f"{API}/forecast/accuracy", f"{API}/users", f"{API}/auth/me"):
        assert anon.get(url).status_code == 401, url
    assert anon.post(f"{D}/plans/recalculate").status_code == 401
    anon.headers["Authorization"] = "Bearer not-a-real-token"
    assert anon.get(f"{D}/plans/current").status_code == 401


def test_login_checks_the_password(anon):
    bad = anon.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    unknown = anon.post(f"{API}/auth/login", json={"username": "nobody", "password": DEMO_PASSWORD})
    assert unknown.status_code == 401 and unknown.json()["detail"] == bad.json()["detail"]   # does not reveal which part was wrong
    ok = anon.post(f"{API}/auth/login", json={"username": "Planner.WH01", "password": DEMO_PASSWORD})   # username is not case sensitive
    assert ok.status_code == 200
    body = ok.json()
    assert body["user"]["role"] == "planner" and body["user"]["warehouse_id"] == "WH01"
    assert "password_hash" not in body["user"] and DEMO_PASSWORD not in str(body["user"])
    anon.headers["Authorization"] = f"Bearer {body['access_token']}"
    assert anon.get(f"{API}/auth/me").json()["username"] == "planner.wh01"


def test_demo_accounts_exist(client):
    users = client.get(f"{API}/users").json()
    names = {u["username"]: u for u in users}
    assert {"admin", "viewer"} <= set(names)
    planners = [u for u in users if u["role"] == "planner"]
    assert len(planners) == 6 and {u["warehouse_id"] for u in planners} == {f"WH0{i}" for i in range(1, 7)}


# ------------------------------------------------------------------ a planner only sees their own warehouse
def test_planner_sees_only_their_warehouse(anon):
    admin_total = None
    sign_in(anon, "admin")
    admin_total = plan_of(anon)["summary"]["orders"]
    sign_in(anon, "planner.wh01")
    plan = plan_of(anon)
    assert 0 < plan["summary"]["orders"] < admin_total
    assert {l["warehouse_id"] for l in plan["lines"]} == {"WH01"}
    assert {t["warehouse_id"] for t in plan["trucks"]} <= {"WH01"} and plan["trucks"]
    assert all(u["warehouse_id"] == "WH01" for u in plan["unassigned"])
    assert {t["warehouse_id"] for t in anon.get(f"{D}/trucks").json()} == {"WH01"}
    assert {o["warehouse_id"] for o in anon.get(f"{D}/plans/{plan['id']}/outlook").json()} <= {"WH01"}
    assert {s["warehouse_id"] for s in anon.get(f"{API}/forecast/skus").json()} == {"WH01"}


def test_planner_accuracy_report_is_cut_to_their_warehouse(anon):
    sign_in(anon, "planner.wh02")
    rep = anon.get(f"{API}/forecast/accuracy").json()
    assert [r["warehouse_id"] for r in rep["by_warehouse"]] == ["WH02"]
    assert set(rep["daily_by_warehouse"]) == {"WH02"} and rep["daily"] == rep["daily_by_warehouse"]["WH02"]
    assert {r["warehouse_id"] for r in rep["by_sku"]} == {"WH02"}
    assert rep["kpis"]["skus"] == len(rep["by_sku"])
    assert anon.get(f"{API}/forecast/accuracy?warehouse_id=WH03").status_code == 403
    sign_in(anon, "admin")
    assert len(anon.get(f"{API}/forecast/accuracy").json()["by_warehouse"]) == 6
    assert len(anon.get(f"{API}/forecast/accuracy?warehouse_id=WH03").json()["by_warehouse"]) == 1


def test_planner_cannot_touch_another_warehouse(anon):
    sign_in(anon, "admin")
    pid = plan_of(anon)["id"]
    foreign = other_warehouse_line(anon, "WH01")
    foreign_truck = next(t for t in anon.get(f"{D}/trucks").json() if t["warehouse_id"] != "WH01")
    sign_in(anon, "planner.wh01")
    oid, wh = foreign["order_id"], foreign["warehouse_id"]
    assert anon.patch(f"{D}/plans/{pid}/lines/{oid}", json={"decision": "REJECTED"}).status_code == 403
    assert anon.patch(f"{D}/plans/{pid}/lines/{oid}/truck", json={"truck_id": None}).status_code == 403
    assert anon.patch(f"{D}/trucks/{foreign_truck['id']}", json={"capacity_units": 5}).status_code == 403
    assert anon.delete(f"{D}/trucks/{foreign_truck['id']}").status_code == 403
    assert anon.post(f"{D}/trucks", json={"name": "Sneaky", "warehouse_id": wh, "capacity_units": 10}).status_code == 403
    assert anon.post(f"{D}/blocked-skus", json={"product_id": foreign["product_id"], "warehouse_id": wh}).status_code == 403
    order = {"order_id": "X1", "order_timestamp": "2026-02-01T10:00:00", "customer_id": "C", "customer_tier": "Basic",
             "product_id": foreign["product_id"], "warehouse_id": wh, "qty_ordered": 1, "due_date": "2026-02-02T10:00:00"}
    assert anon.post(f"{D}/orders", json={"orders": [order]}).status_code == 403
    assert anon.post(f"{D}/plans/{pid}/approve", json={"approved_by": "x", "warehouse_id": wh}).status_code == 403
    sign_in(anon, "admin")                        # nothing changed
    line = next(l for l in plan_of(anon)["lines"] if l["order_id"] == oid)
    assert line["decision"] is None


def test_planner_can_change_their_own_warehouse(anon):
    sign_in(anon, "planner.wh01")
    plan = plan_of(anon)
    line = next(l for l in plan["lines"] if l["final_qty"] > 0)
    r = anon.patch(f"{D}/plans/{plan['id']}/lines/{line['order_id']}", json={"decision": "REJECTED"})
    assert r.status_code == 200
    assert next(l for l in r.json()["lines"] if l["order_id"] == line["order_id"])["decision"] == "REJECTED"
    t = anon.get(f"{D}/trucks").json()[0]
    assert anon.patch(f"{D}/trucks/{t['id']}", json={"capacity_units": 77}).json()["capacity_units"] == 77


# ------------------------------------------------------------------ viewer is read only
def test_viewer_can_read_but_not_change_anything(anon):
    sign_in(anon, "viewer")
    plan = plan_of(anon)
    assert len({l["warehouse_id"] for l in plan["lines"]}) > 1          # sees every warehouse
    line = plan["lines"][0]
    pid = plan["id"]
    assert anon.get(f"{D}/trucks").status_code == 200
    assert anon.get(f"{API}/forecast/accuracy").status_code == 200
    assert anon.patch(f"{D}/plans/{pid}/lines/{line['order_id']}", json={"decision": "REJECTED"}).status_code == 403
    assert anon.post(f"{D}/plans/{pid}/approve", json={"approved_by": "v"}).status_code == 403
    assert anon.post(f"{D}/plans/recalculate").status_code == 403
    assert anon.post(f"{D}/trucks", json={"name": "T", "warehouse_id": "WH01", "capacity_units": 10}).status_code == 403
    assert anon.get(f"{API}/users").status_code == 403


# ------------------------------------------------------------------ approval is per warehouse
def test_planner_approval_sends_only_their_warehouse_and_keeps_the_rest_open(anon):
    sign_in(anon, "admin")
    plan = plan_of(anon)
    other = next(l for l in plan["lines"] if l["warehouse_id"] == "WH02" and l["final_qty"] > 0)
    r = anon.patch(f"{D}/plans/{plan['id']}/lines/{other['order_id']}", json={"decision": "REJECTED"})   # admin's edit on WH02
    assert r.status_code == 200

    sign_in(anon, "planner.wh01")
    mine = plan_of(anon)
    assert mine["summary"]["orders_to_send"] > 0
    done = anon.post(f"{D}/plans/{mine['id']}/approve", json={"approved_by": "Asha"})
    assert done.status_code == 200
    assert done.json()["status"] in ("EXPORTED", "PARTIALLY_EXPORTED")
    logs = anon.get(f"{D}/plans/{mine['id']}/exports").json()
    assert logs and all(l["export_status"] == "SUCCESS" for l in logs)

    sign_in(anon, "admin")
    sent = {l["order_id"] for l in anon.get(f"{D}/plans/{mine['id']}/exports").json()}
    approved_plan = anon.get(f"{D}/plans/{mine['id']}").json()
    wh_of = {l["order_id"]: l["warehouse_id"] for l in approved_plan["lines"]}
    assert sent and {wh_of[o] for o in sent} == {"WH01"}                 # nothing from other warehouses went to the WMS

    nxt = plan_of(anon)
    assert nxt["status"] == "RECOMMENDED" and nxt["id"] != mine["id"]
    again = next(l for l in nxt["lines"] if l["order_id"] == other["order_id"])
    assert again["decision"] == "REJECTED"                               # WH02's edit survived WH01's approval
    assert all(l["status"] == "COMMITTED" for l in nxt["lines"] if l["order_id"] in sent)

    # WH02 can still be approved on its own afterwards
    sign_in(anon, "planner.wh02")
    p2 = plan_of(anon)
    assert anon.post(f"{D}/plans/{p2['id']}/approve", json={"approved_by": "Ravi"}).status_code == 200
    sent2 = {l["order_id"] for l in anon.get(f"{D}/plans/{p2['id']}/exports").json()}
    assert sent2 and other["order_id"] not in sent2 and not (sent2 & sent)


def test_admin_approves_everything_in_one_go(client):
    plan = plan_of(client)
    r = client.post(f"{D}/plans/{plan['id']}/approve", json={"approved_by": "Head office"})
    assert r.status_code == 200
    whs = {l["warehouse_id"] for l in r.json()["lines"] if l["export_status"]}
    assert len(whs) > 1


def test_approved_by_defaults_to_the_signed_in_person(anon):
    sign_in(anon, "planner.wh03")
    p = plan_of(anon)
    r = anon.post(f"{D}/plans/{p['id']}/approve", json={})
    assert r.status_code == 200 and r.json()["approved_by"] == "WH03 Planner"


# ------------------------------------------------------------------ user management
def test_only_admin_manages_users(client):
    made = client.post(f"{API}/users", json={"username": "new.planner", "name": "New", "password": "Secret#123",
                                              "role": "planner", "warehouse_id": "WH04"})
    assert made.status_code == 201 and made.json()["warehouse_id"] == "WH04"
    assert client.post(f"{API}/users", json={"username": "NEW.planner", "name": "Dup", "password": "Secret#123",
                                              "role": "viewer"}).status_code == 409
    assert client.post(f"{API}/users", json={"username": "no.wh", "name": "X", "password": "Secret#123",
                                              "role": "planner"}).status_code == 422
    assert client.post(f"{API}/users", json={"username": "bad.wh", "name": "X", "password": "Secret#123",
                                              "role": "planner", "warehouse_id": "WH99"}).status_code == 422
    assert client.post(f"{API}/users", json={"username": "short", "name": "X", "password": "abc",
                                              "role": "viewer"}).status_code == 422

    other = TestClient(client.app)
    tok = other.post(f"{API}/auth/login", json={"username": "new.planner", "password": "Secret#123"}).json()["access_token"]
    other.headers["Authorization"] = f"Bearer {tok}"
    assert other.get(f"{API}/users").status_code == 403
    assert other.post(f"{API}/users", json={"username": "x.y", "name": "X", "password": "Secret#123", "role": "admin"}).status_code == 403


def test_switching_a_user_off_or_changing_the_password_takes_effect_at_once(client):
    uid = client.post(f"{API}/users", json={"username": "temp.viewer", "name": "Temp", "password": "Secret#123",
                                             "role": "viewer"}).json()["id"]
    other = TestClient(client.app)
    sign_in_with = other.post(f"{API}/auth/login", json={"username": "temp.viewer", "password": "Secret#123"})
    assert sign_in_with.status_code == 200
    other.headers["Authorization"] = f"Bearer {sign_in_with.json()['access_token']}"
    # the admin chose that password, so the viewer picks their own before anything else works
    own = other.post(f"{API}/auth/change-password", json={"current_password": "Secret#123", "new_password": "Secret#123own"})
    assert own.status_code == 200
    other.headers["Authorization"] = f"Bearer {own.json()['access_token']}"
    assert other.get(f"{D}/plans/current").status_code == 200
    assert client.patch(f"{API}/users/{uid}", json={"active": False}).status_code == 200
    assert other.get(f"{D}/plans/current").status_code == 401            # the old token stops working
    assert other.post(f"{API}/auth/login", json={"username": "temp.viewer", "password": "Secret#123own"}).status_code == 401
    client.patch(f"{API}/users/{uid}", json={"active": True, "password": "Another#456"})
    assert other.post(f"{API}/auth/login", json={"username": "temp.viewer", "password": "Secret#123own"}).status_code == 401
    back = other.post(f"{API}/auth/login", json={"username": "temp.viewer", "password": "Another#456"})
    assert back.status_code == 200 and back.json()["user"]["must_change_password"] is True


def test_admin_cannot_lock_themselves_out(client):
    me = client.get(f"{API}/auth/me").json()
    assert client.patch(f"{API}/users/{me['id']}", json={"active": False}).status_code == 422
    assert client.patch(f"{API}/users/{me['id']}", json={"role": "viewer"}).status_code == 422


# ------------------------------------------------------------------ an admin can look at one warehouse
def test_admin_can_narrow_the_view_to_one_warehouse_and_approve_just_that_one(client):
    whole = plan_of(client)
    one = client.get(f"{D}/plans/current?warehouse_id=WH03").json()
    assert {l["warehouse_id"] for l in one["lines"]} == {"WH03"}
    assert one["summary"]["orders"] < whole["summary"]["orders"]
    assert {t["warehouse_id"] for t in client.get(f"{D}/trucks?warehouse_id=WH03").json()} == {"WH03"}
    done = client.post(f"{D}/plans/{whole['id']}/approve", json={"warehouse_id": "WH03"})
    assert done.status_code == 200
    sent_wh = {l["warehouse_id"] for l in client.get(f"{D}/plans/{whole['id']}").json()["lines"] if l["export_status"]}
    assert sent_wh == {"WH03"}
    assert plan_of(client)["status"] == "RECOMMENDED"                     # the other warehouses are still waiting


def test_a_planner_cannot_ask_for_a_different_warehouse_through_the_filter(anon):
    sign_in(anon, "planner.wh01")
    assert anon.get(f"{D}/plans/current?warehouse_id=WH02").status_code == 403
    assert anon.get(f"{D}/trucks?warehouse_id=WH02").status_code == 403
    assert anon.get(f"{D}/plans/current?warehouse_id=WH01").status_code == 200


# ------------------------------------------------------------------ changing your own password
def test_user_can_change_their_own_password(anon):
    login = lambda pw: anon.post(f"{API}/auth/login", json={"username": "planner.wh04", "password": pw})
    sign_in(anon, "planner.wh04")
    old_token = anon.headers["Authorization"]
    cp = f"{API}/auth/change-password"
    assert anon.post(cp, json={"current_password": "wrong", "new_password": "Brand#New1"}).status_code == 422
    assert anon.post(cp, json={"current_password": DEMO_PASSWORD, "new_password": "short"}).status_code == 422
    assert anon.post(cp, json={"current_password": DEMO_PASSWORD, "new_password": DEMO_PASSWORD}).status_code == 422
    r = anon.post(cp, json={"current_password": DEMO_PASSWORD, "new_password": "Brand#New1"})
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    anon.headers["Authorization"] = old_token
    assert anon.get(f"{API}/auth/me").status_code == 401                 # every older sign-in is ended
    anon.headers["Authorization"] = f"Bearer {new_token}"
    assert anon.get(f"{API}/auth/me").status_code == 200                 # this one carries on
    assert login(DEMO_PASSWORD).status_code == 401 and login("Brand#New1").status_code == 200


def test_changing_the_password_needs_a_sign_in(anon):
    assert anon.post(f"{API}/auth/change-password", json={"current_password": "x", "new_password": "Whatever#1"}).status_code == 401


def test_an_admin_reset_ends_the_other_persons_sessions(client):
    uid = next(u["id"] for u in client.get(f"{API}/users").json() if u["username"] == "planner.wh05")
    other = TestClient(client.app)
    sign_in(other, "planner.wh05")
    assert other.get(f"{API}/auth/me").status_code == 200
    assert client.patch(f"{API}/users/{uid}", json={"password": "Reset#Pass9"}).status_code == 200
    assert other.get(f"{API}/auth/me").status_code == 401
