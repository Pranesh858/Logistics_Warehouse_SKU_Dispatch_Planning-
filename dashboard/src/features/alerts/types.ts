export type Severity = 'CRITICAL' | 'WARNING' | 'INFO';
export type AlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED';

export interface Alert {
  id: number;
  kind: string;
  severity: Severity;
  status: AlertStatus;
  title: string;
  detail: string;
  warehouse_id: string | null;
  product_id: number | null;
  occurrences: number;
  first_seen: string | null;
  last_seen: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolved_note: string | null;
  /** JSON of which outside channels this went to, and whether that worked. Null when in-app only. */
  delivery: string | null;
}

export interface AlertSummary {
  open: number;
  acknowledged: number;
  critical: number;
  warning: number;
  total: number;
  worst: Severity | null;
  headline: string | null;
  enabled: boolean;
  /** Outside channels configured. Empty means in-app only, which is a valid setup. */
  channels: string[];
}

export interface DeliveryTest {
  channels: string[];
  ok: boolean;
  results?: Record<string, string>;
  message: string;
}
