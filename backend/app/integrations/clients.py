"""Connections to the outside systems. Every feed has two implementations behind one small interface:

  * a simulator (default) so the whole project runs and can be demonstrated without any external system, and
  * an HTTP client that talks to the real WMS / ERP when WMS_BASE_URL / ERP_BASE_URL are set.

Moving to a real system means pointing the URL at it and, if its field names differ, adjusting the mapping in the
HTTP class (one place per feed). Nothing else in the project knows which one is in use.
"""
import hashlib
from datetime import date, datetime, timedelta
from typing import Protocol

import httpx
import numpy as np
import pandas as pd

from app.core.config import settings
from app.integrations import config_store
from app.modules.forecast.runtime import runtime


class IntegrationError(Exception):
    """The external system could not be reached or answered with something unusable."""


# --------------------------------------------------------------------------- interfaces
class InventorySource(Protocol):
    async def fetch(self) -> list[dict]: ...          # [{product_id, warehouse_id, stock_on_hand}]


class OrderSource(Protocol):
    async def fetch(self, since: datetime | None) -> list[dict]: ...   # OrderIn-shaped dicts


class SalesSource(Protocol):
    async def fetch(self, since: date | None) -> list[dict]: ...       # rows in the dataset-upload format


class PurchaseSink(Protocol):
    async def create(self, po: dict) -> tuple[bool, str | None, str | None]: ...   # ok, erp_reference, error


# --------------------------------------------------------------------------- simulators
class SimulatedInventory:
    """Pretends to be the WMS stock feed: starts from the stock in the sales history, then each call applies a few
    goods receipts and a few pick-downs so the effect of a stock change on the plan can be seen."""

    def __init__(self):
        self.calls = 0
        self.stock: dict[tuple[int, str], float] | None = None

    async def fetch(self) -> list[dict]:
        if self.stock is None:
            snap = runtime.stock_snapshot()
            self.stock = {(int(r.product_id), r.warehouse_id): float(r.stock_on_hand) for r in snap.itertuples()}
        self.calls += 1
        rng = np.random.default_rng(1000 + self.calls)
        keys = list(self.stock)
        for k in rng.choice(len(keys), size=max(1, len(keys) // 10), replace=False):
            key = keys[k]
            delta = float(rng.integers(20, 200)) * (1 if rng.random() < 0.5 else -0.5)
            self.stock[key] = max(0.0, round(self.stock[key] + delta))
        return [{"product_id": p, "warehouse_id": w, "stock_on_hand": q} for (p, w), q in self.stock.items()]


class SimulatedOrders:
    """Pretends to be the ERP order feed: a handful of new customer orders each time it is asked."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, since: datetime | None) -> list[dict]:
        self.calls += 1
        snap = runtime.stock_snapshot()
        rng = np.random.default_rng(5000 + self.calls)
        now = datetime.now().replace(microsecond=0)
        tag = now.strftime("%y%m%d%H%M%S")
        out = []
        for i in range(settings.simulated_orders_per_sync):
            r = snap.iloc[int(rng.integers(0, len(snap)))]
            out.append({
                "order_id": f"ERP-{tag}-{i + 1}", "order_timestamp": now.isoformat(), "customer_id": f"C{int(rng.integers(100, 400))}",
                "customer_tier": str(rng.choice(["Premium", "Standard", "Basic"])), "product_id": int(r.product_id),
                "warehouse_id": r.warehouse_id, "qty_ordered": float(rng.integers(5, 60)),
                "due_date": (now + timedelta(days=int(rng.integers(1, 4)))).isoformat(),
            })
        return out


class SimulatedSales:
    """Pretends to be the ERP sales feed: the next day of sales for every SKU, near its recent average."""

    async def fetch(self, since: date | None) -> list[dict]:
        frame = runtime.frame
        last = frame["date"].max()
        day = last + timedelta(days=1)
        rng = np.random.default_rng(int(day.strftime("%Y%m%d")))
        rows = []
        cols = ["product_id", "product_name", "category", "price", "city", "warehouse_id", "is_organic", "shelf_life_days", "weight_g"]
        for (_, _), g in frame.sort_values("date").groupby(["product_id", "warehouse_id"]):
            tail = g.tail(7)
            base = float(tail["units_sold"].mean())
            sold = max(0.0, round(base * float(rng.normal(1.0, 0.1))))
            stock = max(0.0, float(g["stock_on_hand"].iloc[-1]) - sold)
            row = {c: g[c].iloc[-1] for c in cols}
            row.update(date=day.strftime("%Y-%m-%d"), units_sold=sold, stock_on_hand=stock, discount_pct=0, promotion_flag=0,
                       event_name_1="No Event", event_type_1="No Event")
            rows.append(row)
        return rows


class SimulatedPurchasing:
    async def create(self, po: dict) -> tuple[bool, str | None, str | None]:
        ref = "ERP-PO-" + hashlib.sha256(po["po_ref"].encode()).hexdigest()[:8].upper()
        return True, ref, None


# --------------------------------------------------------------------------- real systems over HTTP
def remap(rows: list[dict], mapping: dict) -> list[dict]:
    """Renames incoming fields, so a system that calls a SKU "sku" still works: {"product_id": "sku"}.
    Fields that are not mentioned are passed through unchanged."""
    if not mapping:
        return rows
    out = []
    for r in rows:
        row = dict(r)
        for ours, theirs in mapping.items():
            if theirs and theirs in r:
                row[ours] = r[theirs]
        out.append(row)
    return out



def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


async def _get(url: str, key: str, params: dict | None = None, transport: httpx.AsyncBaseTransport | None = None):
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as c:
            r = await c.get(url, params=params, headers=_headers(key))
    except httpx.HTTPError as exc:
        raise IntegrationError(f"Cannot reach {url}: {exc}") from exc
    if r.status_code >= 300:
        raise IntegrationError(f"{url} answered HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except ValueError as exc:
        raise IntegrationError(f"{url} did not return JSON") from exc
    return data["items"] if isinstance(data, dict) and "items" in data else data


class HttpInventory:
    """GET {WMS_BASE_URL}/inventory -> [{product_id, warehouse_id, stock_on_hand}]  (or {"items": [...]})"""

    def __init__(self, base: str, key: str, transport=None, mapping: dict | None = None):
        self.base, self.key, self.transport, self.mapping = base.rstrip("/"), key, transport, mapping or {}

    async def fetch(self) -> list[dict]:
        return remap(await _get(f"{self.base}/inventory", self.key, transport=self.transport), self.mapping)


class HttpOrders:
    """GET {ERP_BASE_URL}/orders?since=<ISO time> -> [{order_id, order_timestamp, customer_id, customer_tier,
    product_id, warehouse_id, qty_ordered, due_date}]"""

    def __init__(self, base: str, key: str, transport=None, mapping: dict | None = None):
        self.base, self.key, self.transport, self.mapping = base.rstrip("/"), key, transport, mapping or {}

    async def fetch(self, since: datetime | None) -> list[dict]:
        return remap(await _get(f"{self.base}/orders", self.key, {"since": since.isoformat()} if since else None, self.transport), self.mapping)


class HttpSales:
    """GET {ERP_BASE_URL}/sales?since=<YYYY-MM-DD> -> rows in the dataset-upload format (see README)."""

    def __init__(self, base: str, key: str, transport=None, mapping: dict | None = None):
        self.base, self.key, self.transport, self.mapping = base.rstrip("/"), key, transport, mapping or {}

    async def fetch(self, since: date | None) -> list[dict]:
        return remap(await _get(f"{self.base}/sales", self.key, {"since": since.isoformat()} if since else None, self.transport), self.mapping)


class HttpPurchasing:
    """POST {ERP_BASE_URL}/purchase-orders  {po_ref, warehouse_id, lines:[{product_id, units}]} -> {"reference": "..."}"""

    def __init__(self, base: str, key: str, transport=None, mapping: dict | None = None):
        self.base, self.key, self.transport, self.mapping = base.rstrip("/"), key, transport, mapping or {}

    async def create(self, po: dict) -> tuple[bool, str | None, str | None]:
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport) as c:
                r = await c.post(f"{self.base}/purchase-orders", json=po, headers=_headers(self.key))
        except httpx.HTTPError as exc:
            return False, None, f"ERP unreachable: {exc}"
        if r.status_code >= 300:
            return False, None, f"ERP returned HTTP {r.status_code}: {r.text[:200]}"
        try:
            ref = (r.json() or {}).get("reference")
        except ValueError:
            ref = None
        return True, ref, None


# --------------------------------------------------------------------------- which one is in use
_overrides: dict = {}
_sims: dict = {}


def set_client(feed: str, client) -> None:
    """Used by tests: force a feed to use this client (None puts the default back)."""
    if client is None:
        _overrides.pop(feed, None)
    else:
        _overrides[feed] = client


def reset_simulators() -> None:
    _sims.clear()


def _live_class(feed: str, kind: str, generic_cls):
    """The client for a real system: our generic HTTP contract, or ERPNext's own API."""
    if kind == "erpnext":
        from app.integrations import erpnext
        return {"orders": erpnext.ErpNextOrders, "sales": erpnext.ErpNextSales,
                "purchasing": erpnext.ErpNextPurchasing}.get(feed, generic_cls)
    return generic_cls


def _pick(feed: str, live_cls, sim_cls):
    if feed in _overrides:
        return _overrides[feed]
    base = config_store.base_url(feed)
    if base:
        cls = _live_class(feed, config_store.kind(feed), live_cls)
        return cls(base, config_store.api_key(feed), mapping=config_store.field_map(feed))
    return _sims.setdefault(feed, sim_cls())


def inventory_source() -> InventorySource:
    return _pick("inventory", HttpInventory, SimulatedInventory)


def order_source() -> OrderSource:
    return _pick("orders", HttpOrders, SimulatedOrders)


def sales_source() -> SalesSource:
    return _pick("sales", HttpSales, SimulatedSales)


def purchase_sink() -> PurchaseSink:
    return _pick("purchasing", HttpPurchasing, SimulatedPurchasing)


def mode(feed: str) -> str:
    """'live' when a real system is connected (or forced by a test), else 'simulator'."""
    if feed in _overrides:
        return "live"
    return "live" if config_store.base_url(feed) else "simulator"


# --------------------------------------------------------------------------- testing a connection
SHAPE = {
    "inventory": ("product_id", "warehouse_id", "stock_on_hand"),
    "orders": ("order_id", "product_id", "warehouse_id", "qty_ordered", "due_date", "customer_tier"),
    "sales": ("product_id", "warehouse_id", "date", "units_sold", "stock_on_hand", "price"),
}


async def probe(feed: str, base: str, key: str, mapping: dict, kind: str = "generic") -> dict:
    """Calls the system once and reports what came back, without changing anything. Used by 'Test connection'."""
    cls = _live_class(feed, kind, {"inventory": HttpInventory, "orders": HttpOrders, "sales": HttpSales}[feed])
    client = cls(base, key, mapping=mapping)
    try:
        if feed == "inventory":
            rows = await client.fetch()
        elif kind == "erpnext" and feed == "orders":
            rows = await client.fetch(None, limit=5)       # a look at the latest few, not every order on the site
        else:
            rows = await client.fetch(None)
    except IntegrationError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(rows, list):
        return {"ok": False, "error": "The answer was not a list of records"}
    if not rows:
        return {"ok": True, "rows": 0, "missing": [], "sample": None,
                "note": "The system answered but sent no records. That may be correct if there is nothing new."}
    first = rows[0] if isinstance(rows[0], dict) else {}
    missing = [f for f in SHAPE[feed] if f not in first]
    return {"ok": not missing, "rows": len(rows), "missing": missing, "sample": first,
            "note": "Every field was found." if not missing else
                    "Some fields are missing. Use the field names box to say what this system calls them."}
