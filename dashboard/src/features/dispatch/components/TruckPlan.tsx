'use client';

import { useMemo, useState } from 'react';
import { AlertTriangle, Truck as TruckIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { errorMessage } from '@/lib/api';
import { useMoveToTruck } from '../hooks';
import type { Plan, TruckLoad } from '../types';
import { fmt, fmtDate } from './format';

export function TruckPlan({ plan, editable }: { plan: Plan; editable: boolean }) {
  const move = useMoveToTruck(plan.id);
  const [error, setError] = useState<string | null>(null);

  const byWarehouse = useMemo(() => {
    const m = new Map<string, TruckLoad[]>();
    plan.trucks.forEach((t) => m.set(t.warehouse_id, [...(m.get(t.warehouse_id) ?? []), t]));
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [plan.trucks]);

  const moveOrder = (orderId: string, truckId: number | null) => {
    setError(null);
    move.mutate({ orderId, truckId }, { onError: (e) => setError(errorMessage(e)) });
  };

  if (!plan.trucks.length) {
    return <p className="py-8 text-center text-body-sm text-ink-muted">No trucks are set up. Add them under Trucks, and the plan loads onto them.</p>;
  }

  return (
    <div className="space-y-4">
      {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}

      {plan.unassigned.length > 0 && (
        <section aria-label="Orders without a truck" className="rounded-md border border-warning-border bg-warning-soft p-3">
          <h3 className="flex items-center gap-2 text-h4 text-warning-text">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            {plan.unassigned.length} {plan.unassigned.length === 1 ? 'order has' : 'orders have'} no truck ({fmt(plan.unassigned.reduce((a, u) => a + u.qty, 0))} units)
          </h3>
          <p className="mt-1 text-caption text-warning-text">
            These are not sent until they are on a truck. Add a truck, make one larger, or put the order on a truck that has room.
          </p>
          <ul className="mt-2.5 divide-y divide-warning-border rounded-md bg-surface/80">
            {plan.unassigned.map((u) => (
              <li key={u.order_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 text-body-sm">
                <span>
                  <strong className="font-mono text-caption text-ink-heading">{u.order_id}</strong>{' '}
                  <span className="text-ink-muted">{u.customer_tier}, {u.warehouse_id}, due {fmtDate(u.due_date)}</span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="tabular font-medium">{fmt(u.qty)} units</span>
                  {editable && <MoveSelect trucks={plan.trucks.filter((t) => t.warehouse_id === u.warehouse_id)} current={null} disabled={move.isPending}
                    onPick={(id) => moveOrder(u.order_id, id)} label="Put on truck" />}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {byWarehouse.map(([wh, trucks]) => {
        const used = trucks.filter((t) => t.loaded_units > 0);
        const idle = trucks.filter((t) => t.loaded_units <= 0);
        const loaded = used.reduce((a, t) => a + t.loaded_units, 0);
        return (
          <section key={wh} aria-label={`Warehouse ${wh}`}>
            <h3 className="mb-2 flex items-baseline gap-2.5 text-h3 text-ink-heading">
              {wh}
              <span className="text-caption font-normal text-ink-muted">
                {used.length} of {trucks.length} trucks used, {fmt(loaded)} units
              </span>
            </h3>
            <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
              {used.map((t) => (
                <TruckCard key={t.id} truck={t} siblings={trucks} editable={editable} busy={move.isPending} onMove={moveOrder} />
              ))}
            </div>
            {idle.length > 0 && (
              <p className="mt-2 text-caption text-ink-subtle">Not needed: {idle.map((t) => t.name).join(', ')}</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

function TruckCard({ truck, siblings, editable, busy, onMove }: {
  truck: TruckLoad; siblings: TruckLoad[]; editable: boolean; busy: boolean; onMove: (orderId: string, truckId: number | null) => void;
}) {
  const full = truck.fill_pct >= 95;
  return (
    <article className="overflow-hidden rounded-md border border-surface-line bg-surface">
      <header className="flex items-center justify-between gap-2 px-3 pt-2.5">
        <h4 className="flex items-center gap-1.5 text-h4 text-ink-heading">
          <TruckIcon className="h-4 w-4 text-ink-muted" aria-hidden="true" />{truck.name}
        </h4>
        <span className="tabular text-caption text-ink-muted">{fmt(truck.loaded_units)} / {fmt(truck.capacity_units)} units</span>
      </header>
      <div className="px-3 pt-2">
        <div className="h-1.5 overflow-hidden rounded-pill bg-surface-subtle" role="img" aria-label={`${truck.name} is ${truck.fill_pct}% full`}>
          <div className={`h-full rounded-pill ${full ? 'bg-warning' : 'bg-primary'}`} style={{ width: `${Math.min(truck.fill_pct, 100)}%` }} />
        </div>
        <p className="mt-1 text-caption text-ink-muted">{truck.fill_pct}% full, {fmt(truck.free_units)} units free, {truck.orders.length} {truck.orders.length === 1 ? 'order' : 'orders'}</p>
      </div>
      <ul className="mt-2.5 max-h-64 divide-y divide-surface-line overflow-y-auto border-t border-surface-line">
        {truck.orders.map((o) => (
          <li key={o.order_id} className="flex items-center justify-between gap-2 px-3 py-1 text-body-sm">
            <span className="min-w-0 truncate">
              <span className="font-mono text-caption font-medium text-ink-heading">{o.order_id}</span>{' '}
              <span className="text-ink-subtle">{o.customer_tier}</span>
              {o.manual && <Badge variant="outline" className="ml-2">Your choice</Badge>}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="tabular">{fmt(o.qty)}</span>
              {editable && (
                <MoveSelect trucks={siblings.filter((t) => t.id !== truck.id)} current={o.manual ? truck.id : undefined} disabled={busy}
                  onPick={(id) => onMove(o.order_id, id)} label={`Move ${o.order_id}`} allowAuto={o.manual} compact />
              )}
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function MoveSelect({ trucks, current, disabled, onPick, label, allowAuto, compact }: {
  trucks: TruckLoad[]; current?: number | null; disabled: boolean; onPick: (id: number | null) => void; label: string; allowAuto?: boolean; compact?: boolean;
}) {
  if (!trucks.length && !allowAuto) return null;
  return (
    <select aria-label={label} disabled={disabled} value="" onChange={(e) => {
      const v = e.target.value;
      if (v === '') return;
      onPick(v === 'auto' ? null : Number(v));
    }}
      className={`rounded-md border border-input bg-surface text-caption text-ink-body hover:border-ink-subtle ${compact ? 'h-7 w-20 px-1' : 'h-comp-sm px-2'}`}>
      <option value="">{compact ? 'Move…' : 'Choose truck…'}</option>
      {allowAuto && <option value="auto">Let system choose</option>}
      {trucks.map((t) => <option key={t.id} value={t.id}>{t.name} ({fmt(t.free_units)} free)</option>)}
    </select>
  );
}
