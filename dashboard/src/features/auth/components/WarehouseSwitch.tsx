'use client';

import { useWarehouseList } from '@/features/dispatch/hooks';
import { useAuth, useCan } from '../store';

/** Admins and viewers can narrow a page to one warehouse. A planner never sees this: theirs is fixed. */
export function WarehouseSwitch() {
  const can = useCan();
  const value = useAuth((s) => s.viewWarehouse);
  const set = useAuth((s) => s.setViewWarehouse);
  const list = useWarehouseList();
  if (!can.switchWarehouse) return null;
  return (
    <label className="flex items-center gap-2 text-label text-ink-muted">
      Warehouse
      <select value={value ?? ''} onChange={(e) => set(e.target.value || null)} className="h-9 rounded-md border border-input bg-surface px-2 text-body-sm text-ink-body">
        <option value="">All warehouses</option>
        {(list.data ?? []).map((w) => <option key={w} value={w}>{w}</option>)}
      </select>
    </label>
  );
}
