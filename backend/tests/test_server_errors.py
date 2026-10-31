"""A crash must still reach the dashboard as an error it can read.

Without a handler inside CORS, the 500 had no CORS headers, the browser hid it, and the dashboard told the user the
backend could not be reached while it was running fine.
"""
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@app.get("/__test__/boom", include_in_schema=False)
async def _boom():
    raise RuntimeError("deliberate test failure")


def test_a_crash_answers_with_json_the_browser_may_read():
    origin = settings.cors_origins[0]
    with TestClient(app) as c:
        r = c.get("/__test__/boom", headers={"Origin": origin})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == origin
    assert "Something went wrong on the server" in r.json()["detail"]
    assert "deliberate" not in r.text                     # internals stay in the log
