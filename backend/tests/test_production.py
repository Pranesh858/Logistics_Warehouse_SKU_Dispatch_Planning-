"""The changes that take this from a demo to something that can be deployed:
connections an admin sets, dispatch confirmations, forced password changes, login limits and the audit trail."""
import httpx
import pytest

from app.core import startup_checks
from app.core.config import settings
from app.integrations import clients, config_store
from app.modules.auth.router import reset_failures
from app.modules.dispatch.wms import SimulatedWms, set_wms_client
from tests.conftest import DEMO_PASSWORD, sign_in

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    reset_failures()
    config_store.clear()
    yield
    reset_failures()
    config_store.clear()


# ----------------------------------------------------------------- connections the admin sets
def test_admin_connects_a_system_without_touching_code(client, anon):
    assert client.get(f"{API}/integrations/status").json()["feeds"][0]["mode"] == "simulator"

    body = {"base_url": "https://wms.example.com", "api_key": "secret-key", "enabled": True,
            "field_map": {"inventory": {"product_id": "sku"}}, "sync_minutes": {"inventory": 15}}
    r = client.put(f"{API}/integrations/settings/wms", json=body)
    assert r.status_code == 200
    view = r.json()
    assert view["enabled"] and view["has_key"] and "api_key" not in view        # the key is never sent back
    assert view["source"] == "app" and view["updated_by"] == "admin"

    st = client.get(f"{API}/integrations/status").json()
    inventory = next(f for f in st["feeds"] if f["feed"] == "inventory")
    assert inventory["mode"] == "live" and inventory["auto_minutes"] == 15
    assert st["dispatch_export"]["mode"] == "live"                              # same system, so exports follow
    assert clients.mode("orders") == "simulator"                                # the ERP was not touched

    # saving again without the key keeps it
    client.put(f"{API}/integrations/settings/wms", json={**body, "api_key": None})
    assert config_store.get("wms")["api_key"] == "secret-key"

    # switching it off returns to the simulator
    client.put(f"{API}/integrations/settings/wms", json={"base_url": "https://wms.example.com", "enabled": False})
    assert clients.mode("inventory") == "simulator"

    sign_in(anon, "planner.wh01")
    assert anon.put(f"{API}/integrations/settings/wms", json=body).status_code == 403
    assert anon.get(f"{API}/integrations/settings").status_code == 403


def test_bad_connection_details_are_refused(client):
    assert client.put(f"{API}/integrations/settings/wms", json={"base_url": "", "enabled": True}).status_code == 422
    assert client.put(f"{API}/integrations/settings/wms", json={"base_url": "wms.example.com", "enabled": True}).status_code == 422
    bad_feed = {"base_url": "https://x.test", "enabled": True, "sync_minutes": {"sales": 5}}
    assert client.put(f"{API}/integrations/settings/wms", json=bad_feed).status_code == 422   # sales is an ERP feed
    assert client.put(f"{API}/integrations/settings/erp",
                      json={"base_url": "https://x.test", "enabled": True, "sync_minutes": {"sales": 99999}}).status_code == 422


def test_field_names_can_be_mapped(client):
    rows = [{"sku": 5, "warehouse_id": "WH01", "qty": 12}]
    assert clients.remap(rows, {"product_id": "sku", "stock_on_hand": "qty"})[0]["product_id"] == 5
    assert clients.remap(rows, {})[0] == rows[0]


def test_test_connection_reports_what_came_back(client):
    s = client.get(f"{API}/forecast/skus").json()[0]

    def handler(req: httpx.Request):
        return httpx.Response(200, json=[{"sku": s["product_id"], "warehouse_id": s["warehouse_id"], "qty": 9}])

    clients.set_client("inventory", clients.HttpInventory("http://wms.test", "", transport=httpx.MockTransport(handler)))
    # a probe builds its own client, so point the real one at the mock through the module
    import app.integrations.clients as c
    original = c.HttpInventory
    c.HttpInventory = lambda base, key, transport=None, mapping=None: original(base, key, httpx.MockTransport(handler), mapping)
    try:
        bad = client.post(f"{API}/integrations/settings/test", json={"feed": "inventory", "base_url": "http://wms.test"}).json()
        assert bad["ok"] is False and "product_id" in bad["missing"]
        good = client.post(f"{API}/integrations/settings/test", json={
            "feed": "inventory", "base_url": "http://wms.test", "field_map": {"product_id": "sku", "stock_on_hand": "qty"}}).json()
        assert good["ok"] is True and good["rows"] == 1
    finally:
        c.HttpInventory = original


# ----------------------------------------------------------------- dispatch confirmations
def approve_something(client):
    set_wms_client(SimulatedWms(failure_rate=0.0))
    plan = client.get(f"{API}/dispatch/plans/current").json()
    r = client.post(f"{API}/dispatch/plans/{plan['id']}/approve", json={})
    assert r.status_code == 200
    return r.json()


def reserved_units(client):
    rows = client.get(f"{API}/forecast/orders?days=7&safety=false").json()["rows"]
    return sum(r["reserved"] for r in rows)


def test_shipping_releases_the_reservation(client):
    approve_something(client)
    pending = client.get(f"{API}/integrations/confirmations/pending").json()
    assert pending["count"] > 0
    held_before = reserved_units(client)
    assert held_before > 0                                    # approved orders hold stock back

    out = client.post(f"{API}/integrations/confirmations/all").json()
    assert out["shipped"] == pending["count"] and out["units_released"] > 0
    assert client.get(f"{API}/integrations/confirmations/pending").json()["count"] == 0
    assert reserved_units(client) == 0                        # the goods have gone, so nothing is held twice

    # confirming again changes nothing
    again = client.post(f"{API}/integrations/confirmations", json={"items": [{"order_id": o["order_id"]} for o in pending["orders"][:3]]}).json()
    assert again["shipped"] == 0 and again["skipped"] == 3


def test_cancelling_frees_the_stock_and_drops_the_order(client):
    approve_something(client)
    pending = client.get(f"{API}/integrations/confirmations/pending").json()["orders"]
    first = pending[0]
    out = client.post(f"{API}/integrations/confirmations", json={"items": [{"order_id": first["order_id"], "status": "cancelled"}]}).json()
    assert out["cancelled"] == 1
    plan = client.get(f"{API}/dispatch/plans/current").json()
    assert first["order_id"] not in {l["order_id"] for l in plan["lines"]}


def test_confirmation_webhook_needs_the_key(client, anon, monkeypatch):
    approve_something(client)
    order = client.get(f"{API}/integrations/confirmations/pending").json()["orders"][0]["order_id"]
    body = {"items": [{"order_id": order, "status": "shipped"}]}
    assert anon.post(f"{API}/integrations/webhooks/dispatch-confirmations", json=body).status_code == 503
    monkeypatch.setattr(settings, "integration_webhook_key", "a-long-shared-secret")
    assert anon.post(f"{API}/integrations/webhooks/dispatch-confirmations", json=body).status_code == 401
    ok = anon.post(f"{API}/integrations/webhooks/dispatch-confirmations", json=body, headers={"X-Integration-Key": "a-long-shared-secret"})
    assert ok.status_code == 200 and ok.json()["shipped"] == 1


def test_a_planner_confirms_only_their_own_warehouse(client, anon):
    approve_something(client)
    sign_in(anon, "planner.wh01")
    out = anon.post(f"{API}/integrations/confirmations/all").json()
    left = client.get(f"{API}/integrations/confirmations/pending").json()["orders"]
    assert out["shipped"] > 0 and all(o["warehouse_id"] != "WH01" for o in left)


# ----------------------------------------------------------------- passwords, limits and the audit trail
def test_a_password_someone_else_set_must_be_changed_first(client, anon):
    client.post(f"{API}/users", json={"username": "new.planner", "name": "New Planner", "password": "Temp@12345",
                                      "role": "planner", "warehouse_id": "WH01"})
    r = anon.post(f"{API}/auth/login", json={"username": "new.planner", "password": "Temp@12345"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    anon.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert anon.get(f"{API}/dispatch/plans/current").status_code == 403       # nothing until a new password is set
    assert anon.get(f"{API}/auth/me").status_code == 200                      # except seeing yourself
    changed = anon.post(f"{API}/auth/change-password", json={"current_password": "Temp@12345", "new_password": "MyOwn@98765"})
    assert changed.status_code == 200 and changed.json()["user"]["must_change_password"] is False
    anon.headers["Authorization"] = f"Bearer {changed.json()['access_token']}"
    assert anon.get(f"{API}/dispatch/plans/current").status_code == 200


def test_sign_in_pauses_after_too_many_wrong_passwords(anon, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    for _ in range(3):
        assert anon.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    paused = anon.post(f"{API}/auth/login", json={"username": "admin", "password": DEMO_PASSWORD})
    assert paused.status_code == 429 and "Try again" in paused.json()["detail"]
    reset_failures()
    assert anon.post(f"{API}/auth/login", json={"username": "admin", "password": DEMO_PASSWORD}).status_code == 200


def test_the_audit_trail_records_who_did_what(client, anon):
    approve_something(client)
    client.put(f"{API}/integrations/settings/erp", json={"base_url": "https://erp.example.com", "enabled": True})
    actions = {a["action"] for a in client.get(f"{API}/integrations/audit").json()}
    assert {"login", "plan_approved", "connection_changed"} <= actions
    approved = client.get(f"{API}/integrations/audit?action=plan_approved").json()[0]
    assert approved["username"] == "admin" and "orders" in approved["detail"]
    sign_in(anon, "planner.wh01")
    assert anon.get(f"{API}/integrations/audit").status_code == 403


# ----------------------------------------------------------------- refusing to start unsafely
def test_production_refuses_demo_settings(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    assert startup_checks.problems() == []
    monkeypatch.setattr(settings, "app_env", "production")
    found = " ".join(startup_checks.problems())
    assert "SECRET_KEY" in found and "DEMO_PASSWORD" in found
    with pytest.raises(startup_checks.UnsafeConfiguration):
        startup_checks.check_production_settings()
    monkeypatch.setattr(settings, "secret_key", "x" * 50)
    monkeypatch.setattr(settings, "demo_password", "a-different-one")
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setattr(settings, "auto_create_tables", False)
    assert startup_checks.problems() == []
