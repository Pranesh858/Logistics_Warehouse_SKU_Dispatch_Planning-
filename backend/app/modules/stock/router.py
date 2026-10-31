from fastapi import APIRouter, Query

from app.core.auth import CurrentUser, pick_warehouse
from app.core.deps import DB
from app.modules.stock import service

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/movements")
async def list_movements(db: DB, user: CurrentUser, product_id: int | None = None, warehouse_id: str | None = None,
                         kind: str | None = None, limit: int = Query(200, ge=1, le=1000)):
    """Every change to stock, newest first: receipts, shipments, adjustments and transfers. A planner sees their own
    warehouse only."""
    return await service.movements(db, product_id, pick_warehouse(user, warehouse_id), kind, limit)
