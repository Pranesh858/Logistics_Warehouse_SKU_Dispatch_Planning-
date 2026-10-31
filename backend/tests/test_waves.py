"""Dispatch waves: orders go out on the wave whose cut-off they made; later orders move to the next wave."""
import asyncio
from datetime import datetime

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations import config_store
from app.integrations import service as integration_service
from app.modules.dispatch import waves

API = "/api/v1"
WAVES = "Morning 09:00-10:30; Afternoon 14:00-15:30"
DAY = "2026-11-02"


def at(hhmm: str, day: str = DAY) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00")


@pytest.fixture()
def morning(monkeypatch):
    """Waves on, and the clock standing at 08:00, before the Morning cut-off. Returns a function to move it."""
    monkeypatch.setattr(settings, "dispatch_waves", WAVES)
    now = {"t": at("08:00")}
    monkeypatch.setattr(waves, "clock", lambda: now["t"])

    def move(hhmm: str, day: str = DAY):
        now["t"] = at(hhmm, day)
        return now["t"]
    return move


# ----------------------------------------------------------------- the rules, without the app
def test_an_order_goes_to_the_first_wave_whose_cut_off_it_made(monkeypatch):
    monkeypatch.setattr(settings, "dispatch_waves", WAVES)
    assert waves.wave_of(at("08:59")).key == f"{DAY} Morning"
    assert waves.wave_of(at("09:00")).key == f"{DAY} Afternoon"        # exactly at the cut-off is too late
    assert waves.wave_of(at("13:59")).key == f"{DAY} Afternoon"
    assert waves.wave_of(at("14:00")).key == "2026-11-03 Morning"      # after the last cut-off: next morning
    assert waves.wave_of(at("23:30")).key == "2026-11-03 Morning"


def test_the_plan_is_for_the_first_wave_whose_trucks_have_not_left(monkeypatch):
    monkeypatch.setattr(settings, "dispatch_waves", WAVES)
    assert waves.current(at("09:45")).key == f"{DAY} Morning"          # after its cut-off, before its trucks leave
    assert waves.current(at("10:30")).key == f"{DAY} Afternoon"
    assert waves.current(at("15:30")).key == "2026-11-03 Morning"
    w = waves.current(at("08:00"))
    assert (w.cutoff, w.departure) == (at("09:00"), at("10:30"))
    assert waves.following(waves.current(at("12:00"))).key == "2026-11-03 Morning"
    assert [x.key for x in waves.cutoffs_between(at("08:00"), at("14:00"))] == [f"{DAY} Morning", f"{DAY} Afternoon"]


def test_wave_settings_are_checked():
    assert waves.parse("") == []
    for bad in ("Morning 9-10", "Morning 10:30-09:00", "Late 14:00-15:00; Early 09:00-10:00", "A 09:00-10:00; A 11:00-12:00"):
        with pytest.raises(ValueError):
            waves.parse(bad)


# ----------------------------------------------------------------- through the app
def free_sku(client, wh="WH01"):
    ordered = {ln["product_id"] for ln in client.get(f"{API}/dispatch/plans/current").json()["lines"]
               if ln["warehouse_id"] == wh}
    return next(s for s in client.get(f"{API}/forecast/skus").json()
                if s["warehouse_id"] == wh and s["product_id"] not in ordered and s["stock_on_hand"] >= 50)


def order(oid, sku, placed: datetime, qty=3):
    return {"order_id": oid, "order_timestamp": placed.isoformat(), "customer_id": "C-W", "customer_tier": "Standard",
            "product_id": sku["product_id"], "warehouse_id": sku["warehouse_id"], "qty_ordered": qty,
            "due_date": placed.replace(hour=23, minute=59).isoformat()}


def current(client):
    return client.get(f"{API}/dispatch/plans/current").json()


def test_the_plan_holds_only_this_waves_orders(client, morning):
    sku = free_sku(client)
    r = client.post(f"{API}/dispatch/orders", json={"orders": [
        order("W-EARLY", sku, at("07:30")),                     # Morning
        order("W-LATE", sku, at("09:30")),                      # Afternoon
        order("W-EVENING", sku, at("15:00"))]})                 # next day's Morning
    assert r.status_code == 200, r.text

    plan = current(client)
    assert plan["wave"]["key"] == f"{DAY} Morning" and plan["wave"]["next"]["name"] == "Afternoon"
    ids = {ln["order_id"] for ln in plan["lines"]}
    assert "W-EARLY" in ids and not {"W-LATE", "W-EVENING"} & ids
    assert plan["wave"]["later_wave_orders"] == 2
    early = next(ln for ln in plan["lines"] if ln["order_id"] == "W-EARLY")
    assert early["wave_id"] == f"{DAY} Morning" and early["carried"] is False
    old = [ln for ln in plan["lines"] if ln["order_id"].startswith("ORD")]   # the seed orders are from January
    assert old and all(ln["carried"] for ln in old) and plan["wave"]["carried_orders"] == len(old)


def test_when_the_trucks_leave_the_next_wave_takes_over_and_carries_what_was_not_sent(client, morning):
    sku = free_sku(client)
    client.post(f"{API}/dispatch/orders", json={"orders": [order("W-EARLY", sku, at("07:30")),
                                                           order("W-LATE", sku, at("09:30"))]})
    before = current(client)["version"]

    asyncio.run(integration_service.wave_tick(AsyncSessionLocal, at("08:00"), morning("10:15")))
    assert current(client)["version"] == before                       # Morning trucks have not left: no change

    asyncio.run(integration_service.wave_tick(AsyncSessionLocal, at("10:15"), morning("10:31")))
    plan = current(client)
    assert plan["version"] == before + 1 and plan["trigger"] == "next_wave"
    assert plan["wave"]["key"] == f"{DAY} Afternoon"
    lines = {ln["order_id"]: ln for ln in plan["lines"]}
    assert lines["W-EARLY"]["carried"] is True                         # missed the Morning trucks: carried
    assert lines["W-LATE"]["carried"] is False                         # its own wave now


def test_carried_orders_go_first_within_their_tier(client, morning):
    sku = free_sku(client)
    client.post(f"{API}/integrations/stock", json={
        "items": [{"product_id": sku["product_id"], "warehouse_id": "WH01", "stock_on_hand": 5}]})
    # the newer order is due sooner, so without the carry-over rule it would win the 5 units
    old = order("W-CARRIED", sku, at("08:30"), qty=5)
    new = order("W-NEW", sku, at("09:30"), qty=5)
    new["due_date"] = at("12:00").isoformat()
    client.post(f"{API}/dispatch/orders", json={"orders": [old, new]})
    asyncio.run(integration_service.wave_tick(AsyncSessionLocal, at("08:00"), morning("10:31")))
    lines = {ln["order_id"]: ln for ln in current(client)["lines"]}
    assert lines["W-CARRIED"]["qty_allocated"] == 5 and lines["W-NEW"]["qty_allocated"] == 0


def test_a_cut_off_pulls_the_orders_once_more(client, morning, monkeypatch):
    pulls = []

    async def fake_sync(db):
        pulls.append(waves.clock())
    monkeypatch.setattr(integration_service, "sync_orders", fake_sync)
    monkeypatch.setattr(config_store, "sync_minutes", lambda feed: 120 if feed == "orders" else 0)

    asyncio.run(integration_service.wave_tick(AsyncSessionLocal, at("08:00"), morning("08:30")))
    assert pulls == []                                                  # no cut-off passed
    asyncio.run(integration_service.wave_tick(AsyncSessionLocal, at("08:30"), morning("09:00")))
    assert pulls == [at("09:00")]                                       # the Morning cut-off


def test_pushed_orders_wait_for_the_scheduled_sync(client, morning, monkeypatch):
    monkeypatch.setattr(settings, "integration_webhook_key", "k")
    monkeypatch.setattr(config_store, "sync_minutes", lambda feed: 120 if feed == "orders" else 0)
    sku = free_sku(client)
    before = client.post(f"{API}/dispatch/plans/recalculate").json()["version"]     # a plan for this wave
    r = client.post(f"{API}/integrations/webhooks/orders", headers={"X-Integration-Key": "k"},
                    json={"orders": [order("W-PUSHED", sku, at("07:45"))]})
    assert r.json()["added"] == 1
    plan = current(client)
    assert plan["version"] == before                                   # no new plan per pushed order
    assert plan["wave"]["new_since_plan"] == 1                         # but the page says one is waiting
    assert client.post(f"{API}/dispatch/plans/recalculate").status_code == 200
    assert "W-PUSHED" in {ln["order_id"] for ln in current(client)["lines"]}
