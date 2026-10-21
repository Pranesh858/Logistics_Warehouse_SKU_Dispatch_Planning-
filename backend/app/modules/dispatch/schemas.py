from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderIn(BaseModel):
    order_id: str
    order_timestamp: datetime
    customer_id: str
    customer_tier: str
    product_id: int
    warehouse_id: str
    qty_ordered: float = Field(gt=0)
    due_date: datetime


class OrdersIn(BaseModel):
    orders: list[OrderIn] = Field(min_length=1)


class TruckAssignmentOut(BaseModel):
    truck_id: int
    truck_name: str
    qty: float
    manual: bool = False


class TruckStopOut(BaseModel):
    order_id: str
    qty: float
    manual: bool
    customer_tier: str | None = None
    due_date: datetime | None = None


class TruckLoadOut(BaseModel):
    id: int
    name: str
    warehouse_id: str
    capacity_units: float
    active: bool
    loaded_units: float
    free_units: float
    fill_pct: float
    orders: list[TruckStopOut]


class UnassignedOut(BaseModel):
    order_id: str
    warehouse_id: str
    product_id: int
    customer_tier: str
    due_date: datetime
    qty: float


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    order_timestamp: datetime
    customer_id: str
    customer_tier: str
    product_id: int
    warehouse_id: str
    city: str | None
    due_date: datetime
    wave_id: str | None
    qty_ordered: float
    qty_allocated: float
    qty_short: float
    status: str
    at_risk: bool
    rules_applied: str
    exception_type: str | None
    decision: str | None
    override_qty: float | None
    override_reason: str | None
    final_qty: float = 0           # units the planner would dispatch (after overrides), before truck loading
    send_qty: float = 0            # units that are on a truck, i.e. what is sent to the WMS if approved now
    truck_assignments: list[TruckAssignmentOut] = []
    export_status: str | None = None
    export_error: str | None = None


class PlanOut(BaseModel):
    id: int
    version: int
    status: str
    trigger: str
    created_at: datetime
    approved_by: str | None
    approved_at: datetime | None
    summary: dict
    lines: list[LineOut]
    trucks: list[TruckLoadOut] = []
    unassigned: list[UnassignedOut] = []


class PlanBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    status: str
    trigger: str
    created_at: datetime
    approved_by: str | None
    approved_at: datetime | None


class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(APPROVED|OVERRIDDEN|REJECTED)$")
    override_qty: float | None = Field(default=None, ge=0)
    override_reason: str | None = None


class ApproveIn(BaseModel):
    approved_by: str | None = None          # defaults to the signed-in person
    warehouse_id: str | None = None         # admin only: approve just this warehouse (planners always approve their own)


class BlockIn(BaseModel):
    product_id: int
    warehouse_id: str
    reason: str = ""


class TruckIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    warehouse_id: str = Field(min_length=1, max_length=10)
    capacity_units: float = Field(gt=0)


class TruckUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    capacity_units: float | None = Field(default=None, gt=0)
    active: bool | None = None


class TruckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    warehouse_id: str
    capacity_units: float
    active: bool


class TruckMoveIn(BaseModel):
    truck_id: int | None = None      # null = let the system choose again
