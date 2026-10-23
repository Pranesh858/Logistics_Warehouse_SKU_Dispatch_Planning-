'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useAuth, useScope } from '@/features/auth/store';
import { errorMessage } from '@/lib/api';
import { useApprovePlan } from '../hooks';
import type { Plan } from '../types';
import { fmt } from './format';

export function ApprovePanel({ plan }: { plan: Plan }) {
  const approve = useApprovePlan(plan.id);
  const user = useAuth((s) => s.user);
  const wh = useScope();
  const [open, setOpen] = useState(false);
  const s = plan.summary;
  const where = wh ?? 'all warehouses';

  if (!open) {
    return (
      <Button size="sm" onClick={() => setOpen(true)} disabled={s.orders_to_send === 0}
        title={s.orders_to_send === 0 ? 'Nothing to send right now' : undefined}>
        {wh ? `Approve ${wh}` : 'Approve and send'}
      </Button>
    );
  }

  return (
    <div role="dialog" aria-label="Approve dispatch plan"
      className="absolute right-4 top-14 z-30 w-[min(26rem,calc(100vw-2rem))] rounded-md border border-surface-rule bg-surface p-4 shadow-pop animate-panel-in">
      <p className="text-body font-medium text-ink-heading">
        Send {fmt(s.orders_to_send)} orders ({fmt(s.units_to_send)} units on {fmt(s.trucks_used)} {s.trucks_used === 1 ? 'truck' : 'trucks'}) from {where} to the WMS?
      </p>
      <p className="mt-1 text-caption text-ink-muted">
        Only these orders are sent, with their truck, and their stock is reserved so no later plan can use it again.
        {wh && <> Other warehouses are not affected.</>}
        {s.unassigned_orders > 0 && <> {s.unassigned_orders} order(s) without a truck stay open.</>}
        {s.rejected > 0 && <> {s.rejected} held-back order(s) stay open.</>}
      </p>
      <p className="mt-2.5 text-caption text-ink-body">Approved by <strong className="text-ink-heading">{user?.name}</strong></p>
      {approve.isError && <p role="alert" className="mt-2 text-caption text-danger-text">{errorMessage(approve.error)}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={approve.isPending}>Cancel</Button>
        <Button size="sm" onClick={() => approve.mutate(undefined, { onSuccess: () => setOpen(false) })} disabled={approve.isPending}>
          {approve.isPending ? 'Sending…' : 'Approve and send'}
        </Button>
      </div>
    </div>
  );
}
