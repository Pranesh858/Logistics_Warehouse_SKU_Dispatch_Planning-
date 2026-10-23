'use client';

import { useWarehouseList } from '@/features/dispatch/hooks';
import { useAuth, useCan } from '../store';

/** Admins and viewers can narrow every page to one warehouse. A planner never sees this: theirs is fixed. */
export function WarehouseSwitch() {
  const can = useCan();
  const value = useAuth((s) => s.viewWarehouse);
  const set = useAuth((s) => s.setViewWarehouse);
  const list = useWarehouseList();
  if (!can.switchWarehouse) return null;
  return (
    <label className="flex items-center gap-1.5 text-label text-ink-muted">
      <span className="sr-only sm:not-sr-only">Warehouse</span>
      <select value={value ?? ''} onChange={(e) => set(e.target.value || null)}
        className="h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
        <option value="">All warehouses</option>
        {(list.data ?? []).map((w) => <option key={w} value={w}>{w}</option>)}
      </select>
    </label>
  );
}
