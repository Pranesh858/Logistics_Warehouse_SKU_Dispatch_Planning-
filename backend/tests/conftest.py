import os
import tempfile

# Must be set before the app is imported. Tests use SQLite so no database server is needed. To run them on
# PostgreSQL instead, set TEST_DATABASE_URL to a database made for the purpose: every test drops all its tables.
_url = os.environ.get("TEST_DATABASE_URL", "")
if _url:
    if not _url.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must name a database ending in _test: the tests drop every table in it.")
else:
    _url = f"sqlite+aiosqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"
os.environ["DATABASE_URL"] = _url
# Tests run each request in its own event loop (a second TestClient has its own), and a PostgreSQL connection
# cannot be used from a loop other than the one that opened it. SQLite does not mind, so this only shows there.
if not _url.startswith("sqlite"):
    os.environ["DB_NULL_POOL"] = "true"
os.environ["DEFAULT_TRUCK_CAPACITY"] = "100000"   # old tests: trucks never limit the plan
os.environ["WARM_FORECAST_ON_STARTUP"] = "false"  # tests compute on demand
os.environ["DISPATCH_WAVES"] = ""                 # old tests plan every open order; wave tests set their own
os.environ["PASSWORD_ITERATIONS"] = "1000"        # fast password hashing in tests

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app
from app.modules.dispatch.wms import SimulatedWms, set_wms_client


async def _reset():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


DEMO_PASSWORD = "Dispatch@123"


def sign_in(c: TestClient, username: str) -> None:
    """Log in and send the token with every later call made through this client."""
    r = c.post("/api/v1/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


@pytest.fixture()
def anon():
    """A client that is not signed in."""
    set_wms_client(SimulatedWms(failure_rate=0.0))
    with TestClient(app) as c:
        yield c
        c.portal.call(_reset)
    set_wms_client(None)
    from app.integrations import clients
    from app.modules.forecast.runtime import runtime
    runtime.set_stock({})
    for feed in ("inventory", "orders", "sales", "purchasing"):
        clients.set_client(feed, None)
    clients.reset_simulators()


@pytest.fixture()
def client(anon):
    """Signed in as the admin, so the original dispatch tests run unchanged."""
    sign_in(anon, "admin")
    return anon
