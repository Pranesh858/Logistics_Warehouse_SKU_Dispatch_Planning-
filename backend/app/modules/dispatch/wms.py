"""WMS/ERP adapters. The service only sees `WmsClient.send(order) -> (ok, error)`."""
import hashlib
from typing import Protocol

import httpx

from app.core.config import settings

TRANSIENT_FAILURE_RATE = 0.08


class WmsClient(Protocol):
    async def send(self, payload: dict, attempt: int) -> tuple[bool, str | None]: ...


class SimulatedWms:
    """Stands in for the real WMS (the BRD phase uses synthetic data). A small, deterministic
    fraction of calls fail so retry / FAILED handling is exercised."""

    def __init__(self, failure_rate: float = TRANSIENT_FAILURE_RATE, always_fail: set[str] | None = None):
        self.failure_rate = failure_rate
        self.always_fail = always_fail or set()

    async def send(self, payload: dict, attempt: int) -> tuple[bool, str | None]:
        oid = payload["order_id"]
        if oid in self.always_fail:
            return False, f"WMS rejected order (attempt {attempt})"
        digest = hashlib.sha256(f"{oid}:{attempt}".encode()).digest()
        if digest[0] / 255 < self.failure_rate:
            return False, f"WMS/ERP connection timeout (attempt {attempt})"
        return True, None


class HttpWms:
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def send(self, payload: dict, attempt: int) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.base_url}/dispatch-orders", json=payload, headers=self.headers)
            if r.status_code < 300:
                return True, None
            return False, f"WMS returned HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as exc:
            return False, f"WMS unreachable: {exc}"


_client: WmsClient | None = None


def get_wms_client() -> WmsClient:
    """Follows the connection the admin set in the app; falls back to .env, and to the simulator when neither is set."""
    global _client
    if _client is not None:
        return _client
    from app.integrations import config_store
    base = config_store.base_url("dispatch")
    return HttpWms(base, config_store.api_key("dispatch")) if base else _simulator()


def _simulator() -> WmsClient:
    global _sim
    if _sim is None:
        _sim = SimulatedWms()
    return _sim


_sim: WmsClient | None = None


def set_wms_client(client: WmsClient | None) -> None:
    """Used by tests."""
    global _client, _sim
    _client = client
    _sim = None
