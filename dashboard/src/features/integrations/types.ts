export type FeedKey = 'inventory' | 'orders' | 'sales' | 'purchasing' | 'dispatch';

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

export interface SystemSettings {
  system: 'wms' | 'erp';
  base_url: string;
  enabled: boolean;
  has_key: boolean;
  field_map: Record<string, Record<string, string>>;
  sync_minutes: Record<string, number>;
  source: 'app' | 'env';
  updated_by: string | null;
  updated_at: string | null;
  feeds: string[];
}

export interface IntegrationStatus {
  feeds: Feed[];
  dispatch_export: { system: string; mode: 'simulator' | 'live' };
  live_stock_skus: number;
  webhooks_enabled: boolean;
  awaiting_confirmation: number;
  systems: Record<'wms' | 'erp', SystemSettings>;
  runs: Run[];
}

export interface SystemInput {
  base_url: string;
  api_key?: string | null;
  enabled: boolean;
  field_map: Record<string, Record<string, string>>;
  sync_minutes: Record<string, number>;
}

export interface TestResult {
  ok: boolean;
  error?: string;
  rows?: number;
  missing?: string[];
  sample?: Record<string, unknown> | null;
  note?: string;
}

export interface PendingConfirmations {
  count: number;
  orders: { order_id: string; product_id: number; warehouse_id: string; qty: number; wms_status: string; committed_at: string | null }[];
}

export interface AuditEntry {
  id: number;
  at: string | null;
  username: string;
  role: string;
  action: string;
  warehouse_id: string | null;
  detail: string;
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
