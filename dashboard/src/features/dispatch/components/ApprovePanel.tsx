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
      <div className="flex flex-col items-end gap-1">
        <Button size="lg" onClick={() => setOpen(true)} disabled={s.orders_to_send === 0}>
          {wh ? `Approve ${wh} and send to WMS` : 'Approve all and send to WMS'}
        </Button>
        {s.orders_to_send === 0 && <span className="text-caption text-ink-muted">Nothing to send right now</span>}
      </div>
    );
  }

  return (
    <div role="dialog" aria-label="Approve dispatch plan" className="w-full max-w-md rounded-lg border border-primary bg-surface p-4 shadow-elevated">
      <p className="text-body font-semibold text-ink-heading">
        Send {fmt(s.orders_to_send)} orders ({fmt(s.units_to_send)} units on {fmt(s.trucks_used)} {s.trucks_used === 1 ? 'truck' : 'trucks'}) from {where} to the WMS?
      </p>
      <p className="mt-1 text-body-sm text-ink-muted">
        Only these orders are sent, with their truck, and their stock is reserved so no later plan can use it again.
        {wh && <> Other warehouses are not affected.</>}
        {s.unassigned_orders > 0 && <> {s.unassigned_orders} order(s) without a truck stay open.</>}
        {s.rejected > 0 && <> {s.rejected} held-back order(s) stay open.</>}
      </p>
      <p className="mt-3 text-body-sm text-ink-body">Approved by <strong>{user?.name}</strong></p>
      {approve.isError && <p role="alert" className="mt-2 text-body-sm text-danger-text">{errorMessage(approve.error)}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)} disabled={approve.isPending}>Cancel</Button>
        <Button onClick={() => approve.mutate(undefined, { onSuccess: () => setOpen(false) })} disabled={approve.isPending}>
          {approve.isPending ? 'Sending…' : 'Approve and send'}
        </Button>
      </div>
    </div>
  );
}
