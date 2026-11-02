from fastapi import APIRouter

from app.core.audit import record
from app.core.auth import Planner, ensure_warehouse, pick_warehouse
from app.core.deps import DB
from app.modules.scenarios import service
from app.modules.scenarios.schemas import ScenarioIn

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("/run")
async def run(body: ScenarioIn, db: DB, user: Planner):
    """A simulated plan under the adjustments, and how it differs from the current plan. Changes nothing but the audit
    log. A planner simulates their own warehouse only."""
    wh = pick_warehouse(user, body.warehouse_id)
    for s in body.stock:
        ensure_warehouse(user, s.warehouse_id)
    for b in body.block:
        if b.warehouse_id:
            ensure_warehouse(user, b.warehouse_id)
    out = await service.run(db, body, wh)
    await record(db, user, "scenario_run",
                 f"{len(body.demand)} demand, {len(body.stock)} stock, {len(body.block)} block change(s): fill rate "
                 f"{out['before']['fill_rate_pct']} -> {out['after']['fill_rate_pct']}", wh)
    return out
