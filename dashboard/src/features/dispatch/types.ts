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
