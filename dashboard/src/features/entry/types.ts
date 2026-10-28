export interface NewOrder {
  order_id: string;
  order_timestamp: string;
  customer_id: string;
  customer_tier: 'Premium' | 'Standard' | 'Basic';
  product_id: number;
  warehouse_id: string;
  qty_ordered: number;
  due_date: string;
}

export interface StockCount {
  product_id: number;
  warehouse_id: string;
  stock_on_hand: number;
}

export interface StockResult {
  applied: number;
  changed: number;
  skipped: number;
}
