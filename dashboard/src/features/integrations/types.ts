export type FeedKey = 'inventory' | 'orders' | 'sales' | 'purchasing';

export interface Feed {
  feed: FeedKey;
  label: string;
  system: 'WMS' | 'ERP';
  mode: 'simulator' | 'live';
  auto_minutes: number | null;
  last: { status: 'OK' | 'FAILED'; rows: number; message: string; at: string } | null;
  last_ok_at: string | null;
}

export interface Run {
  id: number;
  feed: FeedKey;
  mode: string;
  status: 'OK' | 'FAILED';
  rows: number;
  message: string;
  at: string;
}

export interface IntegrationStatus {
  feeds: Feed[];
  dispatch_export: { system: string; mode: 'simulator' | 'live' };
  live_stock_skus: number;
  webhooks_enabled: boolean;
  runs: Run[];
}

export interface PurchaseOrder {
  id: number;
  po_ref: string;
  warehouse_id: string;
  status: 'SENT' | 'FAILED';
  erp_reference: string | null;
  total_units: number;
  lines: { product_id: number; product_name: string; units: number; priority: string }[];
  period_days: number;
  safety_buffer: boolean;
  created_by: string;
  error: string | null;
  attempts: number;
  created_at: string | null;
}

export interface PurchaseRequest {
  days: number;
  safety: boolean;
  warehouse_id?: string;
  urgent_only?: boolean;
}
