"""Real servers for tests: the planner and the fake WMS/ERP on real ports, wired to each other.

Used by the tests that must go over real HTTP (tests/test_fake_systems.py, tests/test_load_and_failures.py):
nothing is stubbed between the planner and the fake systems, so they exercise the code a live connection runs.
"""
import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.core.config import settings
from app.integrations import clients, config_store
from app.main import app as planner
from app.modules.dispatch.wms import set_wms_client
from app.modules.forecast.runtime import runtime
from fake_systems import create_app
from tests.conftest import DEMO_PASSWORD, _reset

API = "/api/v1"
WEBHOOK_KEY = "hook-key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    """A uvicorn server in a background thread."""

    def __init__(self, asgi_app, port: int):
        self.server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 120
        while not self.server.started:
            if time.time() > deadline or not self.thread.is_alive():
                raise RuntimeError(f"server on {self.url} did not start")
            time.sleep(0.1)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=60)


class Live:
    def __init__(self, planner_url: str, fake_url: str, fake_state: dict):
        self.app = httpx.Client(base_url=planner_url, timeout=120)
        self.fake = httpx.Client(base_url=fake_url, timeout=120)
        self.state = fake_state
        token = self.app.post(f"{API}/auth/login", json={"username": "admin", "password": DEMO_PASSWORD}).json()
        self.app.headers["Authorization"] = f"Bearer {token['access_token']}"

    def get(self, path, **kw):
        r = self.app.get(f"{API}{path}", **kw)
        assert r.status_code == 200, r.text
        return r.json()

    def post(self, path, expect=200, **kw):
        r = self.app.post(f"{API}{path}", **kw)
        assert r.status_code == expect, r.text
        return r.json()

    def stock(self, pid, wh):
        return next((s["stock_on_hand"] for s in self.get("/forecast/skus")
                     if s["product_id"] == pid and s["warehouse_id"] == wh), None)


@pytest.fixture()
def live_factory(monkeypatch):
    """start(data_dir=None) -> Live. The planner and the fake WMS/ERP on real ports, wired to each other."""
    started = []

    def start(data_dir=None):
        app_port, fake_port = free_port(), free_port()
        fake = create_app(wms_key="wms-key", erp_key="erp-key", app_url=f"http://127.0.0.1:{app_port}",
                          app_webhook_key=WEBHOOK_KEY, **({"data_dir": data_dir} if data_dir else {}))
        fake_url = f"http://127.0.0.1:{fake_port}"
        for name, value in {"wms_base_url": f"{fake_url}/wms", "wms_api_key": "wms-key",
                            "erp_base_url": f"{fake_url}/erp", "erp_api_key": "erp-key",
                            "integration_webhook_key": WEBHOOK_KEY}.items():
            monkeypatch.setattr(settings, name, value)
        config_store.clear()
        clients.reset_simulators()
        set_wms_client(None)                     # the real HTTP client, not the in-process simulator
        servers = [Running(fake, fake_port), Running(planner, app_port)]
        for s in servers:
            s.__enter__()
            started.append(s)
        return Live(servers[1].url, fake_url, fake.state.fake)

    yield start
    for s in reversed(started):
        s.__exit__()
    asyncio.run(_reset())
    runtime.set_stock({})
    config_store.clear()
    clients.reset_simulators()


@pytest.fixture()
def live(live_factory):
    return live_factory()
