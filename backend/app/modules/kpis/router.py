import datetime as dt

from fastapi import APIRouter

from app.core.auth import CurrentUser, pick_warehouse
from app.core.deps import DB
from app.modules.kpis import service
from app.shared.exceptions import BadRequestError

router = APIRouter(prefix="/kpis", tags=["kpis"])


@router.get("")
async def kpis(db: DB, user: CurrentUser, warehouse_id: str | None = None, date_from: dt.date | None = None,
               date_to: dt.date | None = None):
    """Fill rate, order fill rate, on-time share, stock-outs, orders at risk and the service-level target. A planner
    sees their own warehouse only."""
    if date_from and date_to and date_from > date_to:
        raise BadRequestError("date_from is after date_to")
    return await service.compute(db, pick_warehouse(user, warehouse_id), date_from, date_to)
