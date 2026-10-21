'use client';

import { Fragment, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/lib/api';
import { useReviewLine } from '../hooks';
import type { Plan, PlanLine } from '../types';
import { fmt, fmtDate, STATUS_LABEL, STATUS_VARIANT } from './format';

type Filter = 'all' | 'attention' | 'tosend';

export function PlanTable({ plan, editable }: { plan: Plan; editable: boolean }) {
  const review = useReviewLine(plan.id);
  const [filter, setFilter] = useState<Filter>('attention');
  const [tier, setTier] = useState('');
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(40);

  const lines = useMemo(() => {
    const q = search.trim().toLowerCase();
    return plan.lines.filter((l) => {
      if (filter === 'attention' && !(l.exception_type || l.at_risk || l.decision === 'OVERRIDDEN' || l.decision === 'REJECTED')) return false;
      if (filter === 'tosend' && !(l.send_qty > 0)) return false;
      if (tier && l.customer_tier !== tier) return false;
      if (q && !`${l.order_id} ${l.product_id} ${l.warehouse_id} ${l.customer_id}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [plan.lines, filter, tier, search]);

  const send = (l: PlanLine, body: Parameters<typeof review.mutate>[0]['body'], after?: () => void) => {
    setError(null);
    review.mutate({ orderId: l.order_id, body }, {
      onSuccess: () => after?.(),
      onError: (e) => setError(errorMessage(e)),
    });
  };

  const startEdit = (l: PlanLine) => {
    setEditing(l.order_id);
    setQty(String(l.override_qty ?? l.qty_allocated));
    setReason(l.override_reason ?? '');
    setError(null);
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div role="group" aria-label="Filter orders" className="inline-flex rounded-lg border border-input overflow-hidden">
          {([['attention', 'Needs attention'], ['tosend', 'Will be sent'], ['all', 'All orders']] as [Filter, string][]).map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}
              className={`px-3 h-comp-sm text-label ${filter === k ? 'bg-primary text-primary-foreground' : 'bg-surface text-ink-body hover:bg-surface-subtle'}`}>
              {label}
            </button>
          ))}
        </div>
        <select aria-label="Customer tier" value={tier} onChange={(e) => setTier(e.target.value)}
          className="h-comp-sm rounded-md border border-input bg-surface px-2 text-label">
          <option value="">All tiers</option><option>Premium</option><option>Standard</option><option>Basic</option>
        </select>
        <Input aria-label="Search orders" placeholder="Search order, SKU, warehouse" value={search}
          onChange={(e) => setSearch(e.target.value)} className="w-64 h-comp-sm" />
        <span className="text-label text-ink-muted">{lines.length} of {plan.lines.length} orders</span>
      </div>
      {error && <p role="alert" className="mb-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-body-sm">
          <thead>
            <tr className="text-left text-label text-ink-muted border-b border-surface-line">
              <th className="py-2 pr-3">Order</th><th className="pr-3 whitespace-nowrap">Tier</th><th className="pr-3">SKU / warehouse</th>
              <th className="pr-3">Due</th><th className="pr-3 text-right">Ordered</th><th className="pr-3 text-right">Recommended</th>
              <th className="pr-3">Result</th><th className="pr-3">Truck</th><th className="pr-3 text-right">{plan.status === 'RECOMMENDED' ? 'Will send' : 'Sent'}</th>
              <th className="pr-3">{plan.status === 'RECOMMENDED' ? 'Planner' : 'WMS'}</th>
            </tr>
          </thead>
          <tbody>
            {lines.slice(0, shown).map((l) => {
              const locked = l.status === 'COMMITTED';
              return (
                <Fragment key={l.order_id}>
                  <tr className="border-b border-surface-line align-top">
                    <td className="py-2 pr-3 font-medium text-ink-heading">{l.order_id}
                      {l.at_risk && <Badge variant="danger" className="ml-2">At risk</Badge>}</td>
                    <td className="pr-3">{l.customer_tier}</td>
                    <td className="pr-3">#{l.product_id} <span className="text-ink-subtle">{l.warehouse_id}</span></td>
                    <td className="pr-3 whitespace-nowrap">{fmtDate(l.due_date)}</td>
                    <td className="pr-3 text-right tabular-nums">{fmt(l.qty_ordered)}</td>
                    <td className="pr-3 text-right tabular-nums">{fmt(l.qty_allocated)}</td>
                    <td className="pr-3"><Badge variant={STATUS_VARIANT[l.status] ?? 'secondary'}>{STATUS_LABEL[l.status] ?? l.status}</Badge></td>
                    <td className="pr-3 whitespace-nowrap text-ink-body">
                      {l.truck_assignments.length
                        ? l.truck_assignments.map((a) => a.truck_name + (l.truck_assignments.length > 1 ? ` (${fmt(a.qty)})` : '')).join(', ')
                        : l.final_qty > 0 && plan.status === 'RECOMMENDED' ? <Badge variant="warning">No truck</Badge> : <span className="text-ink-subtle">-</span>}
                    </td>
                    <td className="pr-3 text-right tabular-nums font-semibold">{fmt(plan.status === 'RECOMMENDED' ? l.send_qty : l.final_qty)}</td>
                    <td className="pr-3">
                      {plan.status !== 'RECOMMENDED' ? (
                        l.export_status ? (
                          <span title={l.export_error ?? undefined}>
                            <Badge variant={l.export_status === 'SENT' ? 'success' : 'danger'}>
                              {l.export_status === 'SENT' ? 'Sent' : l.export_status === 'FAILED' ? 'Failed' : 'Conflict'}
                            </Badge>
                          </span>
                        ) : <span className="text-ink-subtle">-</span>
                      ) : locked ? (
                        <span className="text-ink-subtle">Locked</span>
                      ) : editable ? (
                        <div className="flex items-center gap-1 whitespace-nowrap">
                          {l.decision && <Badge variant={l.decision === 'REJECTED' ? 'danger' : 'warning'}>{l.decision === 'OVERRIDDEN' ? 'Overridden' : l.decision === 'REJECTED' ? 'Held back' : 'OK'}</Badge>}
                          <Button size="sm" variant="ghost" onClick={() => startEdit(l)}>Override</Button>
                          {l.decision !== 'REJECTED' && l.qty_allocated > 0 && (
                            <Button size="sm" variant="ghost" disabled={review.isPending} onClick={() => send(l, { decision: 'REJECTED' })}>Hold back</Button>
                          )}
                          {(l.decision === 'OVERRIDDEN' || l.decision === 'REJECTED') && (
                            <Button size="sm" variant="ghost" disabled={review.isPending} onClick={() => send(l, { decision: 'APPROVED' })}>Reset</Button>
                          )}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                  {editing === l.order_id && (
                    <tr className="bg-surface-subtle border-b border-surface-line">
                      <td colSpan={10} className="p-3">
                        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
                          e.preventDefault();
                          send(l, { decision: 'OVERRIDDEN', override_qty: Number(qty), override_reason: reason }, () => setEditing(null));
                        }}>
                          <label className="text-label text-ink-muted">Quantity to send (max {fmt(l.qty_ordered)})
                            <Input type="number" min={0} max={l.qty_ordered} step="any" value={qty} onChange={(e) => setQty(e.target.value)} className="mt-1 w-32" required />
                          </label>
                          <label className="text-label text-ink-muted grow">Reason (required)
                            <Input value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1" placeholder="Why are you changing the recommendation?" required />
                          </label>
                          <Button type="submit" size="sm" disabled={review.isPending || !reason.trim()}>Save override</Button>
                          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                        </form>
                      </td>
                    </tr>
                  )}
                  {(l.override_reason || (l.export_error && l.export_status !== 'SENT')) && (
                    <tr className="border-b border-surface-line">
                      <td colSpan={10} className="pb-2 text-caption text-ink-muted">
                        {l.override_reason && <>Reason: {l.override_reason}. </>}
                        {l.export_error && l.export_status !== 'SENT' && <span className="text-danger-text">WMS: {l.export_error}</span>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {lines.length === 0 && (
              <tr><td colSpan={10} className="py-8 text-center text-ink-muted">
                {filter === 'attention' ? 'No orders need attention. Every order is fully covered.' : 'No orders match these filters.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {shown < lines.length && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" size="sm" onClick={() => setShown((n) => n + 60)}>Show more ({lines.length - shown} left)</Button>
        </div>
      )}
    </div>
  );
}
