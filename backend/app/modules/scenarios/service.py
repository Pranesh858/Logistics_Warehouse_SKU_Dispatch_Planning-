"""What-if: the real allocation engine over in-memory copies of the orders and stock.

Nothing stored changes. plan_inputs hands out copies, the engine only reads them, and no plan, ledger row or stock
movement is written. The one write is the audit entry the router adds to say a scenario was run.

The engine plans open orders; it does not use the forecast. So a demand multiplier scales the quantities of open
orders not yet sent, which is how more or less demand would reach a plan.
"""
import asyncio

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dispatch import service as dispatch_service
from app.modules.dispatch.models import PlanLine
from app.modules.forecast.runtime import runtime
from app.modules.kpis.service import summarise
from app.modules.scenarios.schemas import ScenarioIn
from app.shared.exceptions import BadRequestError

COMPARED = ("units_ordered", "units_planned", "fill_rate_pct", "order_fill_rate_pct", "partial", "held", "backordered",
            "blocked", "at_risk")


def _check(body: ScenarioIn, stock: pd.DataFrame, categories: set[str]) -> None:
    """An adjustment naming something unknown would silently do nothing and read as "no effect"."""
    products, warehouses = set(stock["product_id"]), set(stock["warehouse_id"])
    for d in body.demand:
        if d.product_id is not None and d.product_id not in products:
            raise BadRequestError(f"SKU {d.product_id} does not exist")
        if d.category is not None and d.category not in categories:
            raise BadRequestError(f"Category {d.category} does not exist")
    for s in body.stock:
        if s.warehouse_id not in warehouses:
            raise BadRequestError(f"Warehouse {s.warehouse_id} does not exist")
    for b in body.block:
        if b.product_id not in products:
            raise BadRequestError(f"SKU {b.product_id} does not exist")
        if b.warehouse_id is not None and b.warehouse_id not in warehouses:
            raise BadRequestError(f"Warehouse {b.warehouse_id} does not exist")


def _apply(inputs: dict, body: ScenarioIn, category_of: dict[int, str], warehouse_id: str | None) -> dict:
    orders, stock = inputs["orders"].copy(), inputs["stock"].copy()
    if warehouse_id:
        orders = orders[orders["warehouse_id"] == warehouse_id].copy()

    # A multiplier for the SKU wins over one for its category. Orders already sent have left the planner's hands.
    by_sku = {d.product_id: d.multiplier for d in body.demand if d.product_id is not None}
    by_category = {d.category: d.multiplier for d in body.demand if d.category is not None}
    sent = set(inputs["ledger"]["order_id"])

    def factor(o) -> float:
        if o.order_id in sent:
            return 1.0
        return by_sku.get(o.product_id, by_category.get(category_of.get(o.product_id), 1.0))

    orders["qty_ordered"] = [round(o.qty_ordered * factor(o), 2) for o in orders.itertuples()]

    stock["stock_on_hand"] = stock["stock_on_hand"].astype(float)
    for s in body.stock:
        here = stock["warehouse_id"] == s.warehouse_id
        stock.loc[here, "stock_on_hand"] = (stock.loc[here, "stock_on_hand"] * (1 + s.change_pct / 100)).round(2).clip(lower=0)

    blocked = set(inputs["blocked"])
    for b in body.block:
        where = stock[stock["product_id"] == b.product_id]["warehouse_id"]
        blocked |= {(b.product_id, w) for w in where if (b.warehouse_id or warehouse_id or w) == w}
    return {**inputs, "orders": orders, "stock": stock, "blocked": blocked}


def _rows_of(frame: pd.DataFrame) -> list[dict]:
    return [{"qty_ordered": float(r.qty_ordered), "planned": float(r.qty_allocated), "status": r.status, "at_risk": bool(r.at_risk)}
            for r in frame.itertuples()]


async def run(db: AsyncSession, body: ScenarioIn, warehouse_id: str | None) -> dict:
    """The current plan, as the engine recommended it, against the same plan under the adjustments. Planner overrides
    are left out of both, so only the adjustments make a difference."""
    plan = await dispatch_service.current_plan(db)
    baseline: list[dict] = []
    if plan is not None:
        q = select(PlanLine).where(PlanLine.plan_id == plan.id)
        if warehouse_id:
            q = q.where(PlanLine.warehouse_id == warehouse_id)
        baseline = [{"qty_ordered": l.qty_ordered, "planned": l.qty_allocated, "status": l.status, "at_risk": l.at_risk}
                    for l in (await db.execute(q)).scalars()]

    inputs = await dispatch_service.plan_inputs(db)
    stock = inputs["stock"] if inputs else await asyncio.to_thread(runtime.stock_snapshot)
    info = runtime.sku_info()
    _check(body, stock, set(info["category"].dropna()))
    simulated: list[dict] = []
    if inputs is not None:
        changed = _apply(inputs, body, dict(zip(info["product_id"], info["category"])), warehouse_id)
        # verify=False: a stock cut can put the shelf below what is already reserved. In a plan that must stop the
        # build; here it is the answer being asked for.
        simulated = _rows_of(await dispatch_service.allocate_frame(changed, verify=False))

    before, after = summarise(baseline), summarise(simulated)
    return {
        "warehouse_id": warehouse_id, "plan_version": plan.version if plan else None,
        "plan_changes": [c["text"] for c in await dispatch_service.pending_changes(db)],
        # Orders already sent are not rescaled or re-allocated, so with none open every figure reads "no change".
        "open_orders": sum(1 for r in simulated if r["status"] != "COMMITTED"),
        "before": before, "after": after,
        "difference": {k: None if before[k] is None or after[k] is None else round(after[k] - before[k], 2) for k in COMPARED},
    }
