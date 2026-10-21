import type { PlanStatus } from '../types';

export const fmt = (n: number | null | undefined, d = 0) =>
  n === null || n === undefined ? '-' : n.toLocaleString(undefined, { maximumFractionDigits: d });

export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export const STATUS_LABEL: Record<string, string> = {
  FULL: 'Full', PARTIAL: 'Partial', HELD: 'Held whole', BACKORDERED: 'Out of stock',
  BLOCKED: 'Blocked SKU', WAVE_OVERFLOW: 'Over wave capacity', COMMITTED: 'Already sent',
};

export const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'secondary'> = {
  FULL: 'success', PARTIAL: 'warning', HELD: 'warning', BACKORDERED: 'danger',
  BLOCKED: 'danger', WAVE_OVERFLOW: 'warning', COMMITTED: 'secondary',
};

export const PLAN_LABEL: Record<PlanStatus, string> = {
  RECOMMENDED: 'Waiting for your approval',
  SUPERSEDED: 'Replaced by a newer plan',
  EXPORTED: 'Approved and sent to WMS',
  PARTIALLY_EXPORTED: 'Approved, some orders not sent',
  APPROVED_NOTHING_TO_SEND: 'Approved, nothing to send',
};

export const TRIGGER_LABEL: Record<string, string> = {
  startup: 'built automatically at startup',
  new_orders: 'rebuilt automatically when new orders arrived',
  after_approval: 'rebuilt automatically for the orders still open',
  recalculate: 'recalculated on request',
  sku_blocked: 'rebuilt after a SKU was blocked',
  sku_unblocked: 'rebuilt after a SKU was unblocked',
};
