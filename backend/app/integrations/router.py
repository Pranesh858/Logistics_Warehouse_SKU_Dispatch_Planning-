import asyncio
import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import recent, record
from app.core.auth import Admin, CurrentUser, Planner, ensure_warehouse, pick_warehouse, scope
from app.core.config import settings
from app.core.database import get_db
from app.integrations import clients, config_store, service
from app.integrations.models import IntegrationRun, PurchaseOrder
from app.modules.forecast import supply
from app.modules.dispatch.schemas import OrdersIn
from app.shared.exceptions import BadRequestError

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
async def status(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return {**await service.status(db), "runs": await service.recent_runs(db)}


@router.post("/sync/{feed}")
async def sync_now(feed: Literal["inventory", "orders", "sales"], admin: Admin, db: AsyncSession = Depends(get_db)):
    """Pull from the WMS / ERP right now."""
    run = await {"inventory": service.sync_inventory, "orders": service.sync_orders, "sales": service.sync_sales}[feed](db)
    return {"feed": run.feed, "status": run.status, "rows": run.rows, "message": run.message}


# ---- connections an admin configures ---------------------------------------------------------------------------------
class SystemIn(BaseModel):
    base_url: str = ""
    api_key: str | None = None          # leave out to keep the stored key
    enabled: bool = False
    field_map: dict[str, dict[str, str]] = {}
    sync_minutes: dict[str, int] = {}


@router.get("/settings")
async def read_settings(admin: Admin, db: AsyncSession = Depends(get_db)):
    return {s: service._system_view(s) for s in config_store.SYSTEMS}


@router.put("/settings/{system}")
async def write_settings(system: Literal["wms", "erp"], body: SystemIn, admin: Admin, db: AsyncSession = Depends(get_db)):
    """Point the planner at a different WMS or ERP without changing any code."""
    if body.enabled and not body.base_url.strip():
        raise BadRequestError("Enter the system's address before switching it on")
    if body.base_url and not body.base_url.strip().lower().startswith(("http://", "https://")):
        raise BadRequestError("The address must start with http:// or https://")
    allowed = set(config_store.FEEDS_OF[system])
    for key in list(body.field_map) + list(body.sync_minutes):
        if key not in allowed:
            raise BadRequestError(f"{key} is not a feed of the {system.upper()}. Use one of: {', '.join(sorted(allowed))}")
    for feed, minutes in body.sync_minutes.items():
        if minutes < 0 or minutes > 10080:
            raise BadRequestError("Automatic sync must be between 0 (off) and 10080 minutes (a week)")
    await config_store.save(db, system, base_url=body.base_url, api_key=body.api_key, enabled=body.enabled,
                            field_map=body.field_map, sync_minutes=body.sync_minutes, user=admin.username)
    await service._log(db, "inventory" if system == "wms" else "orders", "live" if body.enabled else "simulator", "OK", 0,
                       f"{admin.username} {'connected' if body.enabled else 'disconnected'} the {system.upper()}"
                       + (f" at {body.base_url}" if body.enabled else ""))
    await record(db, admin, "connection_changed",
                 f"{system.upper()} {'connected to ' + body.base_url if body.enabled else 'switched back to the simulator'}")
    return service._system_view(system)


class TestIn(BaseModel):
    feed: Literal["inventory", "orders", "sales"]
    base_url: str | None = None         # leave out to test what is stored
    api_key: str | None = None
    field_map: dict[str, str] = {}


@router.post("/settings/test")
async def test_connection(body: TestIn, admin: Admin):
    """Call the system once and report what came back. Nothing is saved and no data is taken in."""
    system = config_store.SYSTEM_OF[body.feed]
    saved = config_store.get(system)
    base = (body.base_url if body.base_url is not None else saved["base_url"]).strip().rstrip("/")
    if not base:
        raise BadRequestError("Enter the system's address first")
    key = body.api_key if body.api_key is not None else saved["api_key"]
    mapping = body.field_map or (saved.get("field_map") or {}).get(body.feed, {})
    return await clients.probe(body.feed, base, key, mapping)


# ---- purchase orders (raised from Units to order) --------------------------------------------------------------------
class PurchaseIn(BaseModel):
    days: Literal[7, 14, 28] = 7
    safety: bool = True
    warehouse_id: str | None = None
    urgent_only: bool = False


@router.post("/purchase-orders")
async def create_po(body: PurchaseIn, user: Planner, db: AsyncSession = Depends(get_db)):
    """Turn the Units to order list into one purchase order per warehouse and send it to the ERP."""
    wh = pick_warehouse(user, body.warehouse_id)
    pos = await service.create_purchase_orders(db, body.days, body.safety, wh, body.urgent_only, user.username)
    await record(db, user, "purchase_orders_created",
                 f"{len(pos)} order(s), {sum(p.total_units for p in pos)} units, {body.days}-day cover", wh)
    return [service.po_out(p) for p in pos]


@router.get("/purchase-orders")
async def list_po(user: CurrentUser, db: AsyncSession = Depends(get_db), warehouse_id: str | None = None):
    wh = pick_warehouse(user, warehouse_id)
    q = select(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(100)
    if wh:
        q = q.where(PurchaseOrder.warehouse_id == wh)
    return [service.po_out(p) for p in (await db.execute(q)).scalars().all()]


@router.post("/purchase-orders/{po_id}/receive")
async def receive_po(po_id: int, user: Planner, db: AsyncSession = Depends(get_db)):
    """The goods arrived. They stop counting as on order, so ordering stops asking for them again."""
    po = await db.get(PurchaseOrder, po_id)
    if po is not None:
        ensure_warehouse(user, po.warehouse_id)
    out = await supply.receive(db, po_id, user.username)
    await record(db, user, "purchase_order_received", f"{out.po_ref}: {out.total_units} units", out.warehouse_id)
    return service.po_out(out)


@router.post("/purchase-orders/{po_id}/retry")
async def retry_po(po_id: int, user: Planner, db: AsyncSession = Depends(get_db)):
    po = await db.get(PurchaseOrder, po_id)
    if po is not None:
        ensure_warehouse(user, po.warehouse_id)
    return service.po_out(await service.retry_purchase_order(db, po_id))


# ---- stock typed in by a person: a stock count, a goods-in, a correction ---------------------------------------------
class StockCountItem(BaseModel):
    product_id: int
    warehouse_id: str = Field(min_length=1, max_length=10)
    stock_on_hand: float = Field(ge=0)


class StockCountIn(BaseModel):
    items: list[StockCountItem] = Field(min_length=1, max_length=500)
    reason: str = Field(default="", max_length=200)      # kept in the audit trail, e.g. "cycle count aisle 4"


@router.post("/stock")
async def set_stock(body: StockCountIn, user: Planner, db: AsyncSession = Depends(get_db)):
    """Set the units on the shelf for one or more SKUs, for a warehouse with no WMS feed.

    The numbers replace what the system thought was on hand, are stored in the database (so a restart keeps
    them) and the plan is rebuilt if anything changed. A planner can only do this for their own warehouse."""
    items = [{"product_id": i.product_id, "warehouse_id": i.warehouse_id.strip().upper(), "stock_on_hand": i.stock_on_hand}
             for i in body.items]
    for it in items:
        ensure_warehouse(user, it["warehouse_id"])
    applied, changed, skipped = await service.apply_stock(db, items, "manual", user.username, body.reason)
    if not applied:
        raise BadRequestError("None of those SKUs exist at that warehouse. Pick them from the list.")
    await service._log(db, "inventory", "manual", "OK", applied,
                       f"{applied} stock levels set by {user.username}, {changed} changed, {skipped} skipped")
    await record(db, user, "stock_set", f"{applied} level(s), {changed} changed. {body.reason}".strip(),
                 scope(user) or (items[0]["warehouse_id"] if len({i['warehouse_id'] for i in items}) == 1 else None))
    return {"applied": applied, "changed": changed, "skipped": skipped}


# ---- dispatch confirmations: what really happened to approved orders -------------------------------------------------
class ConfirmItem(BaseModel):
    order_id: str
    status: Literal["shipped", "cancelled"] = "shipped"


class ConfirmIn(BaseModel):
    items: list[ConfirmItem]


@router.get("/confirmations/pending")
async def pending(user: CurrentUser, db: AsyncSession = Depends(get_db), warehouse_id: str | None = None):
    rows = await service.pending_confirmations(db, pick_warehouse(user, warehouse_id))
    return {"count": len(rows), "orders": rows}


@router.post("/confirmations")
async def confirm(body: ConfirmIn, user: Planner, db: AsyncSession = Depends(get_db)):
    """Record what happened to approved orders, for a WMS that cannot push confirmations itself."""
    out = await service.confirm_dispatch(db, [i.model_dump() for i in body.items], "manual", scope(user))
    await record(db, user, "dispatch_confirmed", out["message"], scope(user))
    return out


@router.post("/confirmations/all")
async def confirm_all(user: Planner, db: AsyncSession = Depends(get_db), warehouse_id: str | None = None):
    """Mark everything still waiting as shipped."""
    wh = pick_warehouse(user, warehouse_id)
    rows = await service.pending_confirmations(db, wh)
    if not rows:
        raise BadRequestError("Nothing is waiting for confirmation")
    out = await service.confirm_dispatch(db, [{"order_id": r["order_id"], "status": "shipped"} for r in rows], "manual", wh)
    await record(db, user, "dispatch_confirmed", out["message"], wh)
    return out


# ---- webhooks: the WMS / ERP pushes to us instead of us polling -------------------------------------------------------
def _check_key(key: str | None) -> None:
    if not settings.integration_webhook_key:
        raise HTTPException(503, "Webhooks are off. Set INTEGRATION_WEBHOOK_KEY to turn them on.")
    if not key or not hmac.compare_digest(key, settings.integration_webhook_key):
        raise HTTPException(401, "Wrong or missing X-Integration-Key")


class StockIn(BaseModel):
    items: list[dict]


@router.post("/webhooks/inventory")
async def webhook_inventory(body: StockIn, db: AsyncSession = Depends(get_db), x_integration_key: str | None = Header(None)):
    """WMS pushes stock changes: {"items": [{"product_id": 10, "warehouse_id": "WH01", "stock_on_hand": 240}]}"""
    _check_key(x_integration_key)
    applied, changed, skipped = await service.apply_stock(db, body.items, "webhook")
    await service._log(db, "inventory", "webhook", "OK", applied, f"{applied} stock levels pushed, {changed} changed, {skipped} skipped")
    return {"applied": applied, "changed": changed, "skipped": skipped}


@router.post("/webhooks/dispatch-confirmations")
async def webhook_confirmations(body: ConfirmIn, db: AsyncSession = Depends(get_db), x_integration_key: str | None = Header(None)):
    """WMS reports what shipped: {"items": [{"order_id": "O-1", "status": "shipped"}]}"""
    _check_key(x_integration_key)
    return await service.confirm_dispatch(db, [i.model_dump() for i in body.items], "webhook")


@router.post("/webhooks/orders")
async def webhook_orders(body: OrdersIn, db: AsyncSession = Depends(get_db), x_integration_key: str | None = Header(None)):
    """ERP pushes new customer orders (same body as POST /dispatch/orders). Known or invalid orders are skipped."""
    _check_key(x_integration_key)
    # With a scheduled order sync the pushed orders wait for it, so a stream of single orders does not produce a
    # plan version each; without one, the push is the only way orders arrive and the plan is rebuilt at once.
    scheduled = config_store.sync_minutes("orders") > 0
    added, skipped = await service.add_erp_orders(db, [o.model_dump(mode="json") for o in body.orders],
                                                  rebuild=not scheduled)
    await service._log(db, "orders", "webhook", "OK", added, f"{added} orders pushed, {skipped} skipped"
                       + ("; they join the plan at the next order sync" if added and scheduled else ""))
    return {"added": added, "skipped": skipped}


@router.get("/audit")
async def audit(admin: Admin, db: AsyncSession = Depends(get_db), limit: int = Query(100, ge=1, le=500),
                action: str | None = None):
    """Who approved, changed or connected what."""
    return await recent(db, limit, action)
