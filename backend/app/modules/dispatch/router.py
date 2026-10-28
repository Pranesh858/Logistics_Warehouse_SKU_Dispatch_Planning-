from fastapi import APIRouter

from app.core.auth import Admin, CurrentUser, Planner, ensure_warehouse, pick_warehouse, scope
from app.core.deps import DB
from app.core.audit import record
from app.modules.dispatch import service, transfers
from app.modules.dispatch.schemas import (
    ApproveIn, BlockIn, OrdersIn, PlanBrief, PlanOut, ReviewIn, TransferCancelIn, TransferLaneIn,
    TruckIn, TruckMoveIn, TruckOut, TruckUpdate,
)

# Access rules
#   viewer   : read only
#   planner  : reads and changes their own warehouse only (the server enforces it, not the browser)
#   admin    : every warehouse
router = APIRouter(prefix="/dispatch", tags=["dispatch"])


async def _view(db, plan, user, warehouse_id: str | None = None):
    """The plan as this person may see it. An admin or viewer can narrow it to one warehouse with warehouse_id."""
    return await service.plan_view(db, plan, pick_warehouse(user, warehouse_id)) if plan else None


@router.get("/plans/current", response_model=PlanOut | None)
async def current_plan(db: DB, user: CurrentUser, warehouse_id: str | None = None):
    """The recommended plan waiting for the planner (built automatically; nobody has to ask for it)."""
    return await _view(db, await service.current_plan(db), user, warehouse_id)


@router.get("/plans", response_model=list[PlanBrief])
async def plans(db: DB, user: CurrentUser):
    return await service.list_plans(db)


@router.get("/plans/{plan_id}", response_model=PlanOut)
async def plan(plan_id: int, db: DB, user: CurrentUser, warehouse_id: str | None = None):
    return await _view(db, await service.get_plan(db, plan_id), user, warehouse_id)


@router.get("/plans/{plan_id}/outlook")
async def plan_outlook(plan_id: int, db: DB, user: CurrentUser, warehouse_id: str | None = None):
    return await service.outlook(db, await service.get_plan(db, plan_id), pick_warehouse(user, warehouse_id))


@router.post("/plans/recalculate", response_model=PlanOut | None)
async def recalculate(db: DB, user: Planner):
    return await _view(db, await service.recommend_plan(db, trigger="recalculate"), user)


@router.patch("/plans/{plan_id}/lines/{order_id}", response_model=PlanOut)
async def review_line(plan_id: int, order_id: str, body: ReviewIn, db: DB, user: Planner):
    ensure_warehouse(user, await service.line_warehouse(db, plan_id, order_id))
    plan = await service.review_line(db, plan_id, order_id, body.decision, body.override_qty, body.override_reason)
    return await _view(db, plan, user)


@router.patch("/plans/{plan_id}/lines/{order_id}/truck", response_model=PlanOut)
async def move_to_truck(plan_id: int, order_id: str, body: TruckMoveIn, db: DB, user: Planner):
    """Planner puts an order on a chosen truck. truck_id = null hands the choice back to the system."""
    ensure_warehouse(user, await service.line_warehouse(db, plan_id, order_id))
    return await _view(db, await service.move_order_to_truck(db, plan_id, order_id, body.truck_id), user)


@router.post("/plans/{plan_id}/approve", response_model=PlanOut)
async def approve(plan_id: int, body: ApproveIn, db: DB, user: Planner):
    """Planner approval. A planner approves only their own warehouse's orders; an admin approves every warehouse
    (or one, with warehouse_id). Approved lines are sent to the WMS right away; this is the only way anything reaches it."""
    wh = pick_warehouse(user, body.warehouse_id)
    plan = await service.approve_plan(db, plan_id, body.approved_by or user.name, wh)
    view = await _view(db, await service.get_plan(db, plan.id), user, wh)
    sent = view.get("summary", {}) if isinstance(view, dict) else {}
    await record(db, user, "plan_approved",
                 f"plan v{plan.version} ({plan.status}) for {wh or 'all warehouses'}: {sent.get('orders_to_send', '?')} orders", wh)
    return view


@router.post("/plans/{plan_id}/exports/retry", response_model=PlanOut)
async def retry(plan_id: int, db: DB, user: Planner):
    return await _view(db, await service.retry_exports(db, plan_id, scope(user)), user)


@router.get("/plans/{plan_id}/exports")
async def exports(plan_id: int, db: DB, user: CurrentUser, warehouse_id: str | None = None):
    logs = await service.export_log(db, plan_id, pick_warehouse(user, warehouse_id))
    return [{"order_id": l.order_id, "qty": l.qty, "export_status": l.export_status, "attempts": l.attempts,
             "error": l.error, "exported_at": l.exported_at} for l in logs]


@router.post("/orders", response_model=PlanOut)
async def add_orders(body: OrdersIn, db: DB, user: Planner):
    """New orders arrive -> a fresh recommendation is built automatically (still needs approval).
    A planner can only add orders for their own warehouse."""
    for o in body.orders:
        ensure_warehouse(user, o.warehouse_id)
    return await _view(db, await service.ingest_orders(db, body.orders), user)


@router.get("/blocked-skus")
async def blocked(db: DB, user: CurrentUser, warehouse_id: str | None = None):
    return [{"product_id": b.product_id, "warehouse_id": b.warehouse_id, "reason": b.reason}
            for b in await service.list_blocked(db, pick_warehouse(user, warehouse_id))]


@router.post("/blocked-skus", response_model=PlanOut | None)
async def block(body: BlockIn, db: DB, user: Planner):
    ensure_warehouse(user, body.warehouse_id)
    return await _view(db, await service.block_sku(db, body.product_id, body.warehouse_id, body.reason), user)


@router.delete("/blocked-skus/{product_id}/{warehouse_id}", response_model=PlanOut | None)
async def unblock(product_id: int, warehouse_id: str, db: DB, user: Planner):
    ensure_warehouse(user, warehouse_id)
    return await _view(db, await service.unblock_sku(db, product_id, warehouse_id), user)


@router.get("/trucks", response_model=list[TruckOut])
async def trucks(db: DB, user: CurrentUser, include_inactive: bool = False, warehouse_id: str | None = None):
    return await service.list_trucks(db, include_inactive, pick_warehouse(user, warehouse_id))


@router.post("/trucks", response_model=TruckOut, status_code=201)
async def add_truck(body: TruckIn, db: DB, user: Planner):
    """Add a truck. The current recommendation is re-loaded straight away."""
    ensure_warehouse(user, body.warehouse_id)
    return await service.create_truck(db, body.name, body.warehouse_id, body.capacity_units)


@router.patch("/trucks/{truck_id}", response_model=TruckOut)
async def edit_truck(truck_id: int, body: TruckUpdate, db: DB, user: Planner):
    ensure_warehouse(user, await service.truck_warehouse(db, truck_id))
    return await service.update_truck(db, truck_id, body.name, body.capacity_units, body.active)


@router.delete("/trucks/{truck_id}", response_model=TruckOut)
async def remove_truck(truck_id: int, db: DB, user: Planner):
    """Switches the truck off (old plans keep their history)."""
    ensure_warehouse(user, await service.truck_warehouse(db, truck_id))
    return await service.remove_truck(db, truck_id)


# ----------------------------------------------------------------- cross-warehouse transfers
#   A planner sees and acts on transfers that touch their own warehouse, as donor or as destination.
#   Transit times between warehouses are admin settings, like supplier lead times.
@router.get("/transfers")
async def list_transfers(db: DB, user: CurrentUser, warehouse_id: str | None = None, status: str | None = None):
    """Proposed and in-flight stock movements between warehouses."""
    return await transfers.listing(db, pick_warehouse(user, warehouse_id), status)


@router.get("/transfers/summary")
async def transfers_summary(db: DB, user: CurrentUser, warehouse_id: str | None = None):
    return await transfers.summary(db, pick_warehouse(user, warehouse_id))


@router.post("/transfers/{transfer_id}/approve")
async def approve_transfer(transfer_id: int, db: DB, user: Planner):
    """Send the goods. The donor's stock drops now and the plan is rebuilt."""
    out = await transfers.approve(db, transfer_id, user.username, scope(user))
    await record(db, user, "transfer_approved",
                 f"{out['qty']:g} units of SKU {out['product_id']} {out['from_warehouse_id']} -> "
                 f"{out['to_warehouse_id']} (ref {out['transfer_ref']})", out["to_warehouse_id"])
    return out


@router.post("/transfers/{transfer_id}/receive")
async def receive_transfer(transfer_id: int, db: DB, user: Planner):
    """The goods arrived. The destination's stock rises and the shortage can now be filled."""
    out = await transfers.receive(db, transfer_id, user.username, scope(user))
    await record(db, user, "transfer_received",
                 f"{out['qty']:g} units of SKU {out['product_id']} arrived at {out['to_warehouse_id']} "
                 f"(ref {out['transfer_ref']})", out["to_warehouse_id"])
    return out


@router.post("/transfers/{transfer_id}/cancel")
async def cancel_transfer(transfer_id: int, body: TransferCancelIn, db: DB, user: Planner):
    """Drop a proposal, or turn a shipment back. Goods already sent go back on the donor's shelf."""
    out = await transfers.cancel(db, transfer_id, user.username, body.reason, scope(user))
    await record(db, user, "transfer_cancelled",
                 f"ref {out['transfer_ref']}: {body.reason or 'no reason given'}", out["to_warehouse_id"])
    return out


@router.get("/transfer-lanes")
async def transfer_lanes(db: DB, user: CurrentUser):
    """Transit time between each pair of warehouses. Anything unlisted uses the default."""
    return await transfers.list_lanes(db)


@router.put("/transfer-lanes")
async def set_transfer_lane(body: TransferLaneIn, db: DB, user: Admin):
    out = await transfers.set_lane(db, body.from_warehouse_id, body.to_warehouse_id, body.transit_days,
                                   user.username)
    await record(db, user, "transfer_lane_set",
                 f"{body.from_warehouse_id} -> {body.to_warehouse_id}: {body.transit_days} day(s)")
    return out


@router.delete("/transfer-lanes/{from_warehouse_id}/{to_warehouse_id}", status_code=204)
async def clear_transfer_lane(from_warehouse_id: str, to_warehouse_id: str, db: DB, user: Admin):
    await transfers.clear_lane(db, from_warehouse_id, to_warehouse_id)
    await record(db, user, "transfer_lane_cleared", f"{from_warehouse_id} -> {to_warehouse_id}")
