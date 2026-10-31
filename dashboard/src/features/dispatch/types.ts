export type PlanStatus = 'RECOMMENDED' | 'SUPERSEDED' | 'EXPORTED' | 'PARTIALLY_EXPORTED' | 'APPROVED_NOTHING_TO_SEND';
export type Decision = 'APPROVED' | 'OVERRIDDEN' | 'REJECTED';

export interface PlanLine {
  order_id: string;
  order_timestamp: string;
  customer_id: string;
  customer_tier: 'Premium' | 'Standard' | 'Basic';
  product_id: number;
  warehouse_id: string;
  city: string | null;
  due_date: string;
  wave_id: string | null;
  qty_ordered: number;
  qty_allocated: number;
  qty_short: number;
  status: string;
  at_risk: boolean;
  rules_applied: string;
  exception_type: string | null;
  decision: Decision | null;
  override_qty: number | null;
  override_reason: string | null;
  final_qty: number;          // units the planner would dispatch
  send_qty: number;           // units that are on a truck, i.e. what is sent to the WMS
  truck_assignments: TruckAssignment[];
  export_status: 'SENT' | 'FAILED' | 'CONFLICT' | null;
  export_error: string | null;
  carried?: boolean;          // from an earlier dispatch wave and still waiting to go
}

export interface TruckAssignment {
  truck_id: number;
  truck_name: string;
  qty: number;
  manual: boolean;
}

export interface TruckStop {
  order_id: string;
  qty: number;
  manual: boolean;
  customer_tier: string | null;
  due_date: string | null;
}

export interface TruckLoad {
  id: number;
  name: string;
  warehouse_id: string;
  capacity_units: number;
  active: boolean;
  loaded_units: number;
  free_units: number;
  fill_pct: number;
  orders: TruckStop[];
}

export interface Unassigned {
  order_id: string;
  warehouse_id: string;
  product_id: number;
  customer_tier: string;
  due_date: string;
  qty: number;
}

export interface Truck {
  id: number;
  name: string;
  warehouse_id: string;
  capacity_units: number;
  active: boolean;
}

export interface PlanSummary {
  orders: number;
  units_ordered: number;
  units_allocated: number;
  coverage_pct: number;
  units_to_send: number;
  orders_to_send: number;
  units_dispatchable: number;
  trucks_used: number;
  unassigned_orders: number;
  exceptions: number;
  at_risk: number;
  overridden: number;
  rejected: number;
  failed_exports: number;
  by_status: Record<string, number>;
  by_tier: Record<string, { ordered: number; allocated: number; coverage_pct: number }>;
}

export interface Plan {
  id: number;
  version: number;
  status: PlanStatus;
  trigger: string;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  summary: PlanSummary;
  lines: PlanLine[];
  trucks: TruckLoad[];
  unassigned: Unassigned[];
  wave?: WaveInfo | null;     // null when dispatch waves are off
}

/** A dispatch wave: orders placed before the cut-off go out on its trucks. Times are local ISO strings. */
export interface WaveTimes {
  key: string;
  name: string;
  day: string;
  cutoff: string;
  departure: string;
}

export interface WaveInfo extends WaveTimes {
  next: WaveTimes;
  carried_orders: number;     // in this plan, carried over from an earlier wave
  later_wave_orders: number;  // open orders placed for a later wave; not in this plan
  new_since_plan: number;     // orders for this wave that arrived after the plan was built
}

export interface PlanBrief {
  id: number;
  version: number;
  status: PlanStatus;
  trigger: string;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
}

export interface OutlookRow {
  product_id: number;
  warehouse_id: string;
  stock_on_hand: number;
  planned_dispatch: number;
  stock_after_plan: number;
  forecast_demand: number;
  forecast_days: number;
  days_of_cover: number | null;
  outlook: 'OK' | 'LOW_COVER' | 'WILL_STOCK_OUT' | 'STOCKED_OUT';
}

export interface ExportEntry {
  order_id: string;
  qty: number;
  export_status: 'SUCCESS' | 'FAILED' | 'CONFLICT';
  attempts: number;
  error: string | null;
  exported_at: string | null;
}

export interface ReviewBody {
  decision: Decision;
  override_qty?: number;
  override_reason?: string;
}

/** Stock moving from a warehouse that can spare it to one that is short. */
export type TransferStatus = 'PROPOSED' | 'IN_TRANSIT' | 'RECEIVED' | 'CANCELLED';

export interface StockTransfer {
  id: number;
  transfer_ref: string;
  product_id: number;
  from_warehouse_id: string;
  to_warehouse_id: string;
  qty: number;
  transit_days: number;
  status: TransferStatus;
  reason: string;
  short_orders: number;
  earliest_due: string | null;
  eta: string | null;
  created_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  received_by: string | null;
  received_at: string | null;
  cancelled_by: string | null;
  cancel_reason: string | null;
  overdue: boolean;
}

export interface TransferSummary {
  proposed: number;
  proposed_units: number;
  in_transit: number;
  in_transit_units: number;
  overdue: number;
  enabled: boolean;
}

export interface TransferLane {
  from_warehouse_id: string;
  to_warehouse_id: string;
  transit_days: number;
  updated_by: string;
  updated_at: string | null;
}

export interface TransferLanes {
  default_days: number;
  lanes: TransferLane[];
}
