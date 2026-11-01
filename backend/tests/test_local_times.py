"""Every stored time is local time, as order times and the wave cut-offs are.

Columns stamped by the database itself got its clock, which is UTC on SQLite (and on a PostgreSQL in a container),
while the rest of the app writes local time. The dashboard reads them all as local, so in India those showed
5.5 hours early: a sync made at 23:19 was listed at 17:49.
"""
from datetime import datetime, timedelta, timezone

import pytest

API = "/api/v1"
OFFSET = datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)


def close_to_now(iso: str) -> bool:
    return abs(datetime.fromisoformat(iso[:19]) - datetime.now()) < timedelta(minutes=2)


def test_times_the_database_used_to_stamp_are_local(client):
    run = client.post(f"{API}/integrations/sync/orders").json()
    assert run["status"] in ("OK", "FAILED")
    status = client.get(f"{API}/integrations/status").json()
    assert close_to_now(status["runs"][0]["at"]), status["runs"][0]

    plan = client.post(f"{API}/dispatch/plans/recalculate").json()
    assert close_to_now(plan["created_at"]), plan["created_at"]

    saved = client.put(f"{API}/integrations/settings/erp", json={"base_url": "http://erp.test", "enabled": False}).json()
    assert close_to_now(saved["updated_at"])
    if abs(OFFSET) > timedelta(minutes=30):                        # only telling where local time is not UTC
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs(datetime.fromisoformat(plan["created_at"][:19]) - utc_now) > timedelta(minutes=30)


def test_a_changed_setting_moves_its_last_changed_time(client):
    """It was stamped once, when the row was made, and never again: "Last changed" stayed at the first save."""
    from app.integrations.models import IntegrationSetting
    assert IntegrationSetting.__table__.c.updated_at.onupdate is not None
    first = client.put(f"{API}/integrations/settings/erp", json={"base_url": "http://a.test", "enabled": False}).json()
    second = client.put(f"{API}/integrations/settings/erp", json={"base_url": "http://b.test", "enabled": False}).json()
    assert close_to_now(second["updated_at"])
    assert datetime.fromisoformat(second["updated_at"]) > datetime.fromisoformat(first["updated_at"])
