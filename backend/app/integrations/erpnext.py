"""ERPNext as the ERP: the same feeds as the generic HTTP clients, over ERPNext's own REST API.

What the planner and the ERPNext site agree on (scripts/erpnext_seed.py sets it up):
  * item code = our product_id;
  * a warehouse is named "<our warehouse id> - <company abbr>", e.g. "WH01 - DD";
  * the customer group is the customer tier (Premium / Standard / Basic). Any other group plans as Standard.

Customer orders are the submitted Sales Orders. ERPNext puts several items on one order, the planner plans one
product per order, so each item line becomes an order of its own: SAL-ORD-2026-00004-1, -2, ...
Purchase orders from "Units to order" become submitted Purchase Orders. Our po_ref is kept in the Purchase Order's
"Order Confirmation No", so sending the same one twice returns the first instead of ordering twice.

The access key is the ERPNext user's API key and secret together, "key:secret".
"""
import json
import math
from datetime import date, datetime, timedelta

import httpx

from app.core.config import settings
from app.integrations.clients import IntegrationError
from app.modules.dispatch.engine import TIER_RANK

# The planner asks for orders placed since its newest open order. Orders from another source can be newer than an
# ERPNext order not pulled yet, so the window reaches back further; orders already known are skipped anyway.
LOOKBACK = timedelta(days=2)
CLOSED = ["Closed", "Completed", "On Hold"]


def our_warehouse(name: str | None) -> str | None:
    """"WH01 - DD" -> "WH01"."""
    return name.split(" - ")[0].strip() if name else None


class ErpNextClient:
    def __init__(self, base: str, key: str, transport: httpx.AsyncBaseTransport | None = None, mapping: dict | None = None):
        self.base, self.key, self.transport = base.rstrip("/"), key or "", transport
        self._warehouses: dict[str, dict] | None = None

    def _headers(self) -> dict:
        if ":" not in self.key:
            raise IntegrationError("ERPNext needs the API key and the API secret, entered as key:secret")
        return {"Authorization": f"token {self.key}", "Accept": "application/json"}

    async def _call(self, method: str, path: str, **kw):
        url = f"{self.base}{path}"
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport) as c:
                r = await c.request(method, url, headers=self._headers(), **kw)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Cannot reach ERPNext at {self.base}: {exc}") from exc
        if r.status_code >= 300:
            detail = r.text[:300]
            try:
                body = r.json()
                detail = body.get("exception") or body.get("message") or detail
            except ValueError:
                pass
            raise IntegrationError(f"ERPNext answered HTTP {r.status_code} on {path}: {str(detail)[:300]}")
        try:
            return r.json()
        except ValueError as exc:
            raise IntegrationError(f"ERPNext did not return JSON on {path}") from exc

    async def list(self, doctype: str, fields: list[str], filters: list | None = None, order_by: str | None = None,
                   limit: int = 0) -> list[dict]:
        params = {"fields": json.dumps(fields), "limit_page_length": limit}
        if filters:
            params["filters"] = json.dumps(filters)
        if order_by:
            params["order_by"] = order_by
        return (await self._call("GET", f"/api/resource/{doctype}", params=params))["data"]

    async def doc(self, doctype: str, name: str) -> dict:
        return (await self._call("GET", f"/api/resource/{doctype}/{name}"))["data"]

    async def warehouses(self) -> dict[str, dict]:
        """Our warehouse id -> ERPNext's warehouse name and company."""
        if self._warehouses is None:
            rows = await self.list("Warehouse", ["name", "company"], [["is_group", "=", 0]])
            self._warehouses = {our_warehouse(r["name"]): r for r in rows}
        return self._warehouses


class ErpNextOrders(ErpNextClient):
    async def fetch(self, since: datetime | None, limit: int = 0) -> list[dict]:
        filters = [["docstatus", "=", 1], ["status", "not in", CLOSED]]
        if since is not None:
            filters.append(["creation", ">=", (since - LOOKBACK).strftime("%Y-%m-%d %H:%M:%S")])
        heads = await self.list("Sales Order", ["name"], filters, order_by="creation asc", limit=limit)
        out = []
        for h in heads:
            out.extend(self._lines(await self.doc("Sales Order", h["name"])))
        return out

    @staticmethod
    def _lines(so: dict) -> list[dict]:
        placed = datetime.fromisoformat(str(so["creation"])).replace(microsecond=0)
        tier = so.get("customer_group") if so.get("customer_group") in TIER_RANK else "Standard"
        rows = []
        for it in so.get("items") or []:
            try:
                product = int(str(it["item_code"]).strip())
            except (KeyError, ValueError):
                continue                                   # not one of ours: the planner only plans our product ids
            due = it.get("delivery_date") or so.get("delivery_date") or placed.date().isoformat()
            rows.append({
                "order_id": f"{so['name']}-{it.get('idx', len(rows) + 1)}",
                "order_timestamp": placed.isoformat(),
                "customer_id": so.get("customer") or "",
                "customer_tier": tier,
                "product_id": product,
                "warehouse_id": our_warehouse(it.get("warehouse") or so.get("set_warehouse")),
                "qty_ordered": float(it.get("stock_qty") or it.get("qty") or 0),
                "due_date": f"{due}T23:59:00",               # ERPNext gives a day; the order is due by its end
            })
        return rows


class ErpNextPurchasing(ErpNextClient):
    async def create(self, po: dict) -> tuple[bool, str | None, str | None]:
        try:
            return True, await self._create(po), None
        except IntegrationError as exc:
            return False, None, str(exc)

    async def _create(self, po: dict) -> str:
        done = await self.list("Purchase Order", ["name"], [["order_confirmation_no", "=", po["po_ref"]], ["docstatus", "<", 2]])
        if done:
            return done[0]["name"]                          # sent before: the same order, not a second one
        wh = (await self.warehouses()).get(po["warehouse_id"])
        if wh is None:
            raise IntegrationError(f"ERPNext has no warehouse {po['warehouse_id']} (expected one named '{po['warehouse_id']} - ...')")
        when = (date.today() + timedelta(days=settings.default_lead_time_days)).isoformat()
        doc = {"supplier": settings.erpnext_supplier, "company": wh["company"], "transaction_date": date.today().isoformat(),
               "schedule_date": when, "set_warehouse": wh["name"], "order_confirmation_no": po["po_ref"],
               "items": [{"item_code": str(int(ln["product_id"])), "qty": math.ceil(float(ln["units"])),   # units are whole
                          "schedule_date": when, "warehouse": wh["name"]} for ln in po["lines"] if float(ln["units"]) > 0]}
        draft = (await self._call("POST", "/api/resource/Purchase Order", json=doc))["data"]
        done = (await self._call("POST", "/api/method/frappe.client.submit", json={"doc": draft}))["message"]
        return done["name"]


class ErpNextSales(ErpNextClient):
    async def fetch(self, since: date | None) -> list[dict]:
        raise IntegrationError("Sales history is not read from ERPNext yet. Keep this feed on manual (0) and add sales "
                               "with Update sales data on the Demand forecast page.")
