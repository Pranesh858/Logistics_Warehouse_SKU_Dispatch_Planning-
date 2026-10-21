export interface DailyPoint { date: string; predicted: number; actual: number }

export interface Accuracy {
  note: string;
  horizon_days: number;
  origins: string[];
  period: { start: string; end: string };
  target_mape_pct: number;
  warehouse_id?: string;      // set when the report is cut to one warehouse (a planner's own)
  kpis: {
    day_wape: number;
    day_mape_pct: number;
    day_bias_pct: number;
    sku_week_wape: number;
    sku_week_mape_pct: number;
    total_predicted: number;
    total_actual: number;
    sku_day_rows: number;
    skus: number;
  };
  daily: DailyPoint[];
  daily_by_warehouse: Record<string, DailyPoint[]>;
  by_horizon: { horizon_day: number; wape: number; mape_pct: number }[];
  by_warehouse: { warehouse_id: string; wape: number; mape_pct: number; bias_pct: number; predicted: number; actual: number }[];
  by_sku: {
    product_id: number;
    product_name?: string;
    warehouse_id: string;
    forecast_7d: number;
    actual_7d: number;
    mean_abs_err_pct: number | null;
    bias_pct: number | null;
  }[];
}
