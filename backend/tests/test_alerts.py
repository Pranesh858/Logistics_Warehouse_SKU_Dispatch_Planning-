"""Alerts.

What makes an alert list usable is not raising alerts, it is the two things around it: the same problem
appearing once rather than every thirty seconds, and the list emptying itself when conditions clear. A list
that grows forever gets ignored, and an ignored alert is worse than no alert because it looks like cover.
"""
import json
from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.modules.alerts import delivery, rules
from app.modules.alerts import service as alerts
from app.modules.alerts.models import ACKNOWLEDGED, CRITICAL, OPEN, RESOLVED, WARNING, Alert
from tests.conftest import sign_in

API = "/api/v1"


def run(client, coro_fn):
    """Run something against the app's own session, from inside a sync test."""
    from app.core.database import AsyncSessionLocal

    async def go():
        async with AsyncSessionLocal() as db:
            return await coro_fn(db)

    return client.portal.call(go)


def raise_one(client, key="stockout:1:WH01", **kw):
    body = dict(key=key, kind="stockout", severity=CRITICAL, title="SKU 1 is out of stock at WH01",
                detail="Nothing free to sell.", warehouse_id="WH01", product_id=1)
    body.update(kw)
    return run(client, lambda db: alerts.raise_alert(db, **body))


def listing(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"{API}/alerts" + (f"?{q}" if q else ""))
    assert r.status_code == 200, r.text
    return r.json()


# ----------------------------------------------------------------- one row per problem
def test_the_same_problem_twice_is_one_alert_with_a_count(client):
    raise_one(client)
    raise_one(client)
    raise_one(client)
    rows = [a for a in listing(client) if a["kind"] == "stockout"]
    assert len(rows) == 1, "a condition noticed every sweep must not fill the list"
    assert rows[0]["occurrences"] == 3
    assert rows[0]["status"] == OPEN


def test_two_different_problems_are_two_alerts(client):
    raise_one(client, key="stockout:1:WH01", product_id=1)
    raise_one(client, key="stockout:2:WH02", product_id=2, warehouse_id="WH02")
    assert len([a for a in listing(client) if a["kind"] == "stockout"]) == 2


def test_the_last_seen_time_moves_with_each_occurrence(client):
    first = raise_one(client)
    first_seen, last_seen = first.first_seen, first.last_seen
    again = raise_one(client)
    assert again.first_seen == first_seen, "the problem started when it started"
    assert again.last_seen >= last_seen


# ----------------------------------------------------------------- it clears itself
def test_clearing_a_condition_takes_it_off_the_list(client):
    raise_one(client)
    assert run(client, lambda db: alerts.clear(db, "stockout:1:WH01")) is True
    assert not [a for a in listing(client) if a["kind"] == "stockout"]
    resolved = listing(client, status="RESOLVED")
    assert any(a["dedupe_key"] if "dedupe_key" in a else a["title"] for a in resolved)


def test_clearing_something_that_was_never_wrong_does_nothing(client):
    assert run(client, lambda db: alerts.clear(db, "stockout:999:WH09")) is False


def test_a_sweep_closes_what_it_no_longer_finds(client):
    raise_one(client, key="stockout:1:WH01")
    raise_one(client, key="stockout:2:WH02", product_id=2, warehouse_id="WH02")
    # the next sweep only still finds the first one
    closed = run(client, lambda db: alerts.clear_missing(db, "stockout", {"stockout:1:WH01"}))
    assert closed == 1
    live = [a for a in listing(client) if a["kind"] == "stockout"]
    assert [a["product_id"] for a in live] == [1]


def test_a_problem_that_comes_back_is_reopened_not_duplicated(client):
    raise_one(client)
    run(client, lambda db: alerts.clear(db, "stockout:1:WH01"))
    again = raise_one(client)
    assert again.status == OPEN
    assert again.resolved_at is None
    assert again.occurrences == 2
    assert len([a for a in listing(client) if a["kind"] == "stockout"]) == 1


def test_reopening_forgets_the_earlier_acknowledgement(client):
    a = raise_one(client)
    run(client, lambda db: alerts.acknowledge(db, a.id, "planner1"))
    run(client, lambda db: alerts.clear(db, "stockout:1:WH01"))
    again = raise_one(client)
    assert again.acknowledged_by is None, "a new occurrence has not been looked at by anyone yet"


# ----------------------------------------------------------------- acting on one
def test_acknowledging_keeps_it_on_the_list(client):
    a = raise_one(client)
    r = client.post(f"{API}/alerts/{a.id}/acknowledge")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == ACKNOWLEDGED
    assert r.json()["acknowledged_by"] == "admin"
    assert any(x["id"] == a.id for x in listing(client)), \
        "somebody looking at it does not mean the stock arrived"


def test_acknowledging_twice_is_refused(client):
    a = raise_one(client)
    assert client.post(f"{API}/alerts/{a.id}/acknowledge").status_code == 200
    assert client.post(f"{API}/alerts/{a.id}/acknowledge").status_code == 422


def test_resolving_by_hand_records_who_and_why(client):
    a = raise_one(client)
    r = client.post(f"{API}/alerts/{a.id}/resolve", json={"note": "stock counted wrong, it is on the shelf"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == RESOLVED
    assert r.json()["resolved_note"] == "stock counted wrong, it is on the shelf"
    assert not any(x["id"] == a.id for x in listing(client))


def test_resolving_by_hand_does_not_hide_a_problem_that_is_still_true(client):
    """Closing an alert is not a fix. The next sweep finds the condition again and says so."""
    a = raise_one(client)
    client.post(f"{API}/alerts/{a.id}/resolve", json={"note": "ignoring it"})
    again = raise_one(client)
    assert again.status == OPEN


def test_an_unknown_alert_is_a_404(client):
    assert client.post(f"{API}/alerts/999999/acknowledge").status_code == 404


# ----------------------------------------------------------------- what each person sees
def test_worst_first(client):
    raise_one(client, key="a:1", severity="INFO", title="Just so you know")
    raise_one(client, key="a:2", severity=WARNING, title="Getting low")
    raise_one(client, key="a:3", severity=CRITICAL, title="Out of stock")
    assert [a["severity"] for a in listing(client)][:3] == [CRITICAL, WARNING, "INFO"]


def test_the_summary_drives_the_badge(client):
    raise_one(client, key="a:1", severity=CRITICAL)
    raise_one(client, key="a:2", severity=WARNING)
    r = client.get(f"{API}/alerts/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["total"] == 2
    assert body["critical"] == 1 and body["warning"] == 1
    assert body["worst"] == CRITICAL
    assert body["headline"]
    assert body["channels"] == [], "nothing is configured in a test install, so in-app only"


def test_a_planner_sees_their_own_warehouse_and_anything_global(anon):
    sign_in(anon, "admin")
    raise_one(anon, key="wh1:1", warehouse_id="WH01")
    raise_one(anon, key="wh2:1", warehouse_id="WH02")
    raise_one(anon, key="global:1", kind="sync_failed", warehouse_id=None, product_id=None,
              title="The sales feed is failing")

    r = anon.get(f"{API}/users")
    planners = [u for u in r.json() if u["role"] == "planner" and u.get("warehouse_id") == "WH01"]
    if not planners:
        pytest.skip("no planner scoped to WH01 in this install")
    sign_in(anon, planners[0]["username"])
    if anon.get(f"{API}/auth/me").status_code == 403:
        pytest.skip("this planner must change their password first")

    mine = anon.get(f"{API}/alerts").json()
    seen = {a["title"] for a in mine}
    assert "The sales feed is failing" in seen, \
        "an alert with no warehouse concerns everyone; hiding it means nobody acts on it"
    assert all(a["warehouse_id"] in (None, "WH01") for a in mine)


def test_a_viewer_can_read_alerts_but_not_act_on_them(anon):
    sign_in(anon, "admin")
    a = raise_one(anon)
    viewers = [u for u in anon.get(f"{API}/users").json() if u["role"] == "viewer"]
    if not viewers:
        pytest.skip("no viewer account in this install")
    sign_in(anon, viewers[0]["username"])
    if anon.get(f"{API}/auth/me").status_code == 403:
        pytest.skip("this viewer must change their password first")
    assert anon.get(f"{API}/alerts").status_code == 200
    assert anon.post(f"{API}/alerts/{a.id}/acknowledge").status_code == 403


# ----------------------------------------------------------------- housekeeping
def test_resolved_alerts_are_forgotten_eventually(client):
    a = raise_one(client)
    run(client, lambda db: alerts.clear(db, "stockout:1:WH01"))

    async def age_it(db):
        row = await db.get(Alert, a.id)
        row.resolved_at = datetime.now() - timedelta(days=90)
        await db.commit()

    run(client, age_it)
    assert run(client, lambda db: alerts.prune(db, days=30)) == 1
    assert run(client, lambda db: db.get(Alert, a.id)) is None


def test_switching_alerts_off_raises_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "alerts_enabled", False)
    assert raise_one(client) is None
    assert client.get(f"{API}/alerts/summary").json()["enabled"] is False


# ----------------------------------------------------------------- the rules
def test_a_sweep_runs_every_rule_and_survives_one_failing(client):
    r = client.post(f"{API}/alerts/sweep")
    assert r.status_code == 200, r.text
    body = r.json()
    for rule in ("feeds", "stock", "exports", "transfers", "retrain"):
        assert rule in body, f"the sweep must cover {rule}"
    assert "live" in body


def test_a_failing_feed_raises_an_alert_and_a_good_run_clears_it(client):
    from app.integrations.models import IntegrationRun

    async def fail(db):
        db.add(IntegrationRun(feed="sales", mode="simulator", status="FAILED", rows=0,
                              message="connection refused"))
        await db.commit()

    run(client, fail)
    run(client, rules.check_feeds)
    rows = [a for a in listing(client) if a["kind"] == "sync_failed"]
    assert len(rows) == 1
    assert "sales" in rows[0]["title"]
    assert "connection refused" in rows[0]["detail"]
    assert rows[0]["warehouse_id"] is None, "a broken feed is nobody's warehouse and everybody's problem"

    async def succeed(db):
        db.add(IntegrationRun(feed="sales", mode="simulator", status="OK", rows=10, message="fine"))
        await db.commit()

    run(client, succeed)
    run(client, rules.check_feeds)
    assert not [a for a in listing(client) if a["kind"] == "sync_failed"]


def test_an_overdue_transfer_is_flagged(client):
    from app.modules.dispatch.models import StockTransfer

    async def seed(db):
        db.add(StockTransfer(transfer_ref="TR-LATE", product_id=1, from_warehouse_id="WH01",
                             to_warehouse_id="WH02", qty=50, transit_days=1, status="IN_TRANSIT",
                             reason="seeded", short_orders=1,
                             eta=datetime.now() - timedelta(days=3)))
        await db.commit()

    run(client, seed)
    run(client, rules.check_transfers)
    rows = [a for a in listing(client) if a["kind"] == "transfer_overdue"]
    assert len(rows) == 1
    assert "TR-LATE" in rows[0]["title"]
    assert rows[0]["warehouse_id"] == "WH02", "the warehouse waiting for it is the one that cares"


def test_a_transfer_that_is_not_late_yet_is_not_flagged(client):
    from app.modules.dispatch.models import StockTransfer

    async def seed(db):
        db.add(StockTransfer(transfer_ref="TR-SOON", product_id=1, from_warehouse_id="WH01",
                             to_warehouse_id="WH02", qty=50, transit_days=1, status="IN_TRANSIT",
                             reason="seeded", short_orders=1,
                             eta=datetime.now() + timedelta(days=2)))
        await db.commit()

    run(client, seed)
    run(client, rules.check_transfers)
    assert not [a for a in listing(client) if a["kind"] == "transfer_overdue"]


def test_the_stock_rule_flags_what_will_run_out(client):
    """On the demo data this should find real shortages; if it finds none, it must not invent any."""
    run(client, rules.check_stock)
    rows = [a for a in listing(client) if a["kind"] in ("stockout", "low_cover")]
    for a in rows:
        assert a["product_id"] is not None and a["warehouse_id"] is not None
        assert a["severity"] in (CRITICAL, WARNING)
        assert "order" in a["detail"].lower(), "an alert should say what to do about it"
    assert len(rows) <= rules.STOCK_ALERT_LIMIT, "one bad day must not bury the list"


# ----------------------------------------------------------------- delivery
def test_nothing_configured_means_in_app_only(client):
    assert delivery.channels() == []
    r = client.post(f"{API}/alerts/test-delivery")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "app only" in r.json()["message"]


def test_a_webhook_is_used_once_it_is_set(client, monkeypatch):
    sent = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            sent.update(url=url, body=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.invalid/hook")
    monkeypatch.setattr(settings, "alert_webhook_key", "s3cret")
    monkeypatch.setattr(delivery.httpx, "Client", FakeClient)

    assert delivery.channels() == ["webhook"]
    raise_one(client)
    assert sent["url"] == "https://example.invalid/hook"
    assert sent["headers"]["X-Alert-Key"] == "s3cret"
    assert sent["body"]["severity"] == CRITICAL
    assert sent["body"]["title"].startswith("SKU 1 is out of stock")
    assert "text" in sent["body"], "chat tools read text; monitoring tools read the fields"


def test_a_repeat_is_not_delivered_again(client, monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.invalid/hook")
    monkeypatch.setattr(delivery, "_send_webhook", lambda alert: calls.append(alert.dedupe_key))

    raise_one(client)
    raise_one(client)
    raise_one(client)
    assert len(calls) == 1, "a failing feed must not send a message every thirty seconds"


def test_a_problem_coming_back_is_delivered_again(client, monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.invalid/hook")
    monkeypatch.setattr(delivery, "_send_webhook", lambda alert: calls.append(alert.dedupe_key))

    raise_one(client)
    run(client, lambda db: alerts.clear(db, "stockout:1:WH01"))
    raise_one(client)
    assert len(calls) == 2, "it came back, so it is news again"


def test_a_delivery_failure_is_recorded_and_does_not_lose_the_alert(client, monkeypatch):
    def boom(alert):
        raise RuntimeError("no route to host")

    monkeypatch.setattr(settings, "alert_webhook_url", "https://example.invalid/hook")
    monkeypatch.setattr(delivery, "_send_webhook", boom)

    a = raise_one(client)
    assert a is not None, "an alert that cannot be delivered is still an alert"
    rows = [x for x in listing(client) if x["id"] == a.id]
    assert len(rows) == 1
    assert "no route to host" in json.loads(rows[0]["delivery"])["webhook"]


def test_only_an_admin_tests_delivery(anon):
    sign_in(anon, "admin")
    planners = [u for u in anon.get(f"{API}/users").json() if u["role"] == "planner"]
    if not planners:
        pytest.skip("no planner account in this install")
    sign_in(anon, planners[0]["username"])
    if anon.get(f"{API}/auth/me").status_code == 403:
        pytest.skip("this planner must change their password first")
    assert anon.post(f"{API}/alerts/test-delivery").status_code == 403
