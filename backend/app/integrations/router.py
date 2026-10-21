import asyncio
import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Admin, CurrentUser, Planner, ensure_warehouse, pick_warehouse
from app.core.config import settings
from app.core.database import get_db
from app.integrations import service
from app.integrations.models import IntegrationRun, PurchaseOrder
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
    return [service.po_out(p) for p in pos]


@router.get("/purchase-orders")
async def list_po(user: CurrentUser, db: AsyncSession = Depends(get_db), warehouse_id: str | None = None):
    wh = pick_warehouse(user, warehouse_id)
    q = select(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(100)
    if wh:
        q = q.where(PurchaseOrder.warehouse_id == wh)
    return [service.po_out(p) for p in (await db.execute(q)).scalars().all()]


@router.post("/purchase-orders/{po_id}/retry")
async def retry_po(po_id: int, user: Planner, db: AsyncSession = Depends(get_db)):
    po = await db.get(PurchaseOrder, po_id)
    if po is not None:
        ensure_warehouse(user, po.warehouse_id)
    return service.po_out(await service.retry_purchase_order(db, po_id))


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


@router.post("/webhooks/orders")
async def webhook_orders(body: OrdersIn, db: AsyncSession = Depends(get_db), x_integration_key: str | None = Header(None)):
    """ERP pushes new customer orders (same body as POST /dispatch/orders). Known or invalid orders are skipped."""
    _check_key(x_integration_key)
    added, skipped = await service.add_erp_orders(db, [o.model_dump(mode="json") for o in body.orders])
    await service._log(db, "orders", "webhook", "OK", added, f"{added} orders pushed, {skipped} skipped")
    return {"added": added, "skipped": skipped}
