export interface SkuRow {
  product_id: number;
  warehouse_id: string;
  city: string;
  category: string;
  stock_on_hand: number;
}

export interface ForecastTotal {
  product_id: number;
  warehouse_id: string;
  city: string;
  total_predicted_units: number;
  total_low: number | null;
  total_high: number | null;
  forecast_days: number;
}

export interface ForecastDay {
  product_id: number;
  warehouse_id: string;
  date: string;
  predicted_units: number;
  predicted_low?: number;
  predicted_high?: number;
}

export interface ForecastResult {
  days: number;
  grand_total: number;
  totals: ForecastTotal[];
  daywise: ForecastDay[];
  model: { objective: string; training_rows: number; wape: number; mape_pct: number };
}

export interface Driver {
  driver: string;
  factor: number;
  effect_pct: number;
  reason: string;
}

export interface ExplainResult {
  product_id: number;
  warehouse_id: string;
  city: string;
  days: number;
  total_predicted_units: number;
  total_range_80pct: [number, number];
  recent_actuals: { date: string; units_sold: number }[];
  forecast: {
    date: string;
    predicted_units: number;
    range_80pct: [number, number];
    baseline_units: number;
    drivers: Driver[];
  }[];
}

export interface ForecastRequest {
  days: number;
  product_ids?: number[];
  warehouse_ids?: string[];
}

export interface OrderRow {
  product_id: number;
  lead_time_days: number;
  cover_days: number;
  period_units: number;
  on_order: number;
  product_name: string;
  category: string;
  warehouse_id: string;
  city: string;
  forecast_units: number;
  forecast_high: number;
  stock_on_hand: number;
  reserved: number;
  available: number;
  days_of_cover: number | null;
  units_to_order: number;
  priority: 'Order now' | 'Order soon' | 'Plan ahead' | 'Covered';
}

export interface OrdersResult {
  days: number;
  safety_buffer: boolean;
  warehouse_id: string | null;
  history_to: string;
  default_lead_time_days: number;
  on_order_units: number;
  summary: { skus_to_order: number; units_to_order: number; order_now: number; order_soon: number; forecast_units: number; skus_checked: number };
  by_warehouse: { warehouse_id: string; city: string; skus: number; units: number }[];
  rows: OrderRow[];
}

export interface DatasetPreview {
  filename: string;
  errors: string[];
  warnings: string[];
  rows?: number;
  date_from?: string;
  date_to?: string;
  skus?: number;
  new_product_ids?: number[];
  new_sku_warehouse_pairs?: number;
  short_history_pairs?: { product_id: number; warehouse_id: string }[];
  overlap_rows?: number;
  extends_history?: boolean;
  current_history_to?: string;
}

export interface DatasetStatus {
  state: 'idle' | 'ready' | 'running' | 'done' | 'failed' | 'rejected';
  reason?: string;
  /** What the last run retrained on: an uploaded file, or the history as it stands (Retrain now / the schedule). */
  kind?: 'upload' | 'history';
  step?: string;
  progress?: number;
  preview?: DatasetPreview | null;
  error?: string | null;
  result?: {
    promoted: boolean;
    comparison: {
      wape_before: number | null; wape_after: number; change_pct: number; worse: boolean; holdout_days: number;
      /** The history was the bundled 120-day sample (no full sales file), so a new model is bound to score worse. */
      history_is_sample?: boolean;
    };
    left_out: number;
    products?: number;
    history_to?: string;
    new_product_ids?: number[];
  } | null;
}

export type ReportKind = 'forecast' | 'orders' | 'accuracy';

export interface LeadTimes {
  default_days: number;
  skus: { product_id: number; lead_time_days: number; supplier: string; updated_by: string; updated_at: string | null }[];
}
