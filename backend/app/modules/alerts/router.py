from fastapi import APIRouter

from app.core.audit import record
from app.core.auth import Admin, CurrentUser, Planner, pick_warehouse, scope
from app.core.deps import DB
from app.modules.alerts import delivery, rules, service
from app.modules.alerts.schemas import ResolveIn

# Access rules
#   viewer   : reads the list (seeing a problem is not changing anything)
#   planner  : acknowledges and resolves alerts for their own warehouse, plus the global ones
#   admin    : every warehouse, and the delivery test
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(db: DB, user: CurrentUser, warehouse_id: str | None = None, status: str | None = None):
    """Live alerts, worst first. Alerts with no warehouse concern everybody and are shown to everybody."""
    return await service.listing(db, pick_warehouse(user, warehouse_id), status)


@router.get("/summary")
async def alerts_summary(db: DB, user: CurrentUser, warehouse_id: str | None = None):
    """Counts for the badge in the header, and which delivery channels are configured."""
    return await service.summary(db, pick_warehouse(user, warehouse_id))


@router.post("/{alert_id}/acknowledge")
async def acknowledge(alert_id: int, db: DB, user: Planner):
    """Say somebody is on it. The alert stays until the condition itself clears."""
    out = await service.acknowledge(db, alert_id, user.username, scope(user))
    await record(db, user, "alert_acknowledged", out["title"], out["warehouse_id"])
    return out


@router.post("/{alert_id}/resolve")
async def resolve(alert_id: int, body: ResolveIn, db: DB, user: Planner):
    """Close it by hand. If the condition is still true the next sweep raises it again, which is intended."""
    out = await service.resolve(db, alert_id, user.username, body.note, scope(user))
    await record(db, user, "alert_resolved", f"{out['title']}: {out['resolved_note']}", out["warehouse_id"])
    return out


@router.post("/sweep")
async def sweep_now(db: DB, user: Planner):
    """Re-check every rule immediately, instead of waiting for the next scheduled sweep."""
    return await rules.sweep(db)


@router.post("/test-delivery")
async def test_delivery(db: DB, user: Admin):
    """Send one test alert to every configured channel, so delivery is proved before it is needed."""
    import asyncio
    out = await asyncio.to_thread(delivery.probe)
    await record(db, user, "alert_delivery_tested", out["message"])
    return out
