export interface DemandChange { product_id?: number; category?: string; multiplier: number }
export interface StockChange { warehouse_id: string; change_pct: number }
export interface BlockChange { product_id: number; warehouse_id?: string }

export interface ScenarioIn {
  demand: DemandChange[];
  stock: StockChange[];
  block: BlockChange[];
  warehouse_id?: string;
}

export interface ScenarioSummary {
  orders: number;
  orders_fully_planned: number;
  units_ordered: number;
  units_planned: number;
  fill_rate_pct: number | null;
  order_fill_rate_pct: number | null;
  partial: number;
  held: number;
  backordered: number;
  blocked: number;
  at_risk: number;
}

export interface ScenarioResult {
  warehouse_id: string | null;
  plan_version: number | null;
  plan_changes: string[];      // what happened since the current plan was built, so it may differ for that reason too
  open_orders: number;         // orders not yet sent; a change can only act on these
  before: ScenarioSummary;
  after: ScenarioSummary;
  difference: Record<string, number | null>;
}
