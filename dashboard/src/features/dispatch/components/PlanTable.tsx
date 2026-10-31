'use client';

import { Fragment, useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Empty, Rail, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { errorMessage } from '@/lib/api';
import { useReviewLine } from '../hooks';
import type { Plan, PlanLine } from '../types';
import { fmt, fmtDate, STATUS_LABEL, STATUS_VARIANT } from './format';

type Filter = 'attention' | 'tosend' | 'all';

const FILTERS: [Filter, string][] = [['attention', 'Needs attention'], ['tosend', 'Will be sent'], ['all', 'All orders']];

const rail = (l: PlanLine): Rail => {
  if (l.export_status === 'FAILED' || l.export_status === 'CONFLICT') return 'bad';
  if (l.at_risk || l.status === 'BACKORDERED' || l.status === 'BLOCKED') return 'bad';
  if (l.exception_type || l.decision === 'OVERRIDDEN' || l.decision === 'REJECTED') return 'warn';
  return 'none';
};

/** Every order in the plan, what the engine decided, and the planner's chance to disagree. */
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

  const draft = plan.status === 'RECOMMENDED';

  const lines = useMemo(() => {
    const q = search.trim().toLowerCase();
    return plan.lines.filter((l) => {
      // an order carried over has already missed one wave: it needs a look as much as a shortage does
      if (filter === 'attention' && !(l.exception_type || l.at_risk || l.carried || l.decision === 'OVERRIDDEN' || l.decision === 'REJECTED')) return false;
      if (filter === 'tosend' && !(l.send_qty > 0)) return false;
      if (tier && l.customer_tier !== tier) return false;
      if (q && !`${l.order_id} ${l.product_id} ${l.warehouse_id} ${l.customer_id}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [plan.lines, filter, tier, search]);

  const send = (l: PlanLine, body: Parameters<typeof review.mutate>[0]['body'], after?: () => void) => {
    setError(null);
    review.mutate({ orderId: l.order_id, body }, { onSuccess: () => after?.(), onError: (e) => setError(errorMessage(e)) });
  };

  const startEdit = (l: PlanLine) => {
    setEditing(l.order_id);
    setQty(String(l.override_qty ?? l.qty_allocated));
    setReason(l.override_reason ?? '');
    setError(null);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Filter orders" className="inline-flex overflow-hidden rounded-md border border-surface-rule">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => { setFilter(k); setShown(40); }}
              className={`h-comp-sm border-r border-surface-rule px-2.5 text-caption font-medium last:border-0 transition-colors ${
                filter === k ? 'bg-primary text-primary-foreground' : 'bg-surface text-ink-body hover:bg-surface-subtle'}`}>
              {label}
            </button>
          ))}
        </div>
        <select aria-label="Customer tier" value={tier} onChange={(e) => setTier(e.target.value)}
          className="h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
          <option value="">All tiers</option><option>Premium</option><option>Standard</option><option>Basic</option>
        </select>
        <Input aria-label="Search orders" placeholder="Order, SKU or warehouse" value={search}
          onChange={(e) => setSearch(e.target.value)} className="h-comp-sm w-56 text-caption" />
        <span className="ml-auto text-caption text-ink-subtle">{lines.length} of {plan.lines.length} orders</span>
      </div>

      {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}

      <TableFrame>
        <Table>
          <THead>
            <tr>
              <TH>Order</TH><TH>Tier</TH><TH>SKU</TH><TH>Due</TH>
              <TH align="right">Ordered</TH><TH align="right">Recommended</TH>
              <TH>Result</TH><TH>Truck</TH><TH align="right">{draft ? 'Will send' : 'Sent'}</TH>
              <TH>{draft ? 'Planner' : 'WMS'}</TH>
            </tr>
          </THead>
          <tbody>
            {lines.slice(0, shown).map((l) => {
              const locked = l.status === 'COMMITTED';
              return (
                <Fragment key={l.order_id}>
                  <TR rail={rail(l)}>
                    <TD strong className="whitespace-nowrap">
                      <span className="font-mono text-caption">{l.order_id}</span>
                      {l.at_risk && <Badge variant="danger" className="ml-1.5">At risk</Badge>}
                      {l.carried && <Badge variant="outline" className="ml-1.5" title={l.wave_id ? `Placed for the ${l.wave_id} wave` : undefined}>Carried over</Badge>}
                    </TD>
                    <TD muted>{l.customer_tier}</TD>
                    <TD className="whitespace-nowrap"><span className="font-mono text-caption">#{l.product_id}</span> <span className="text-ink-subtle">{l.warehouse_id}</span></TD>
                    <TD muted className="whitespace-nowrap">{fmtDate(l.due_date)}</TD>
                    <TD align="right">{fmt(l.qty_ordered)}</TD>
                    <TD align="right">{fmt(l.qty_allocated)}</TD>
                    <TD><Badge variant={STATUS_VARIANT[l.status] ?? 'secondary'}>{STATUS_LABEL[l.status] ?? l.status}</Badge></TD>
                    <TD className="whitespace-nowrap">
                      {l.truck_assignments.length
                        ? l.truck_assignments.map((a) => a.truck_name + (l.truck_assignments.length > 1 ? ` (${fmt(a.qty)})` : '')).join(', ')
                        : l.final_qty > 0 && draft ? <Badge variant="warning">No truck</Badge> : <span className="text-ink-subtle">—</span>}
                    </TD>
                    <TD align="right" strong>{fmt(draft ? l.send_qty : l.final_qty)}</TD>
                    <TD>
                      {!draft ? (
                        l.export_status ? (
                          <span title={l.export_error ?? undefined}>
                            <Badge variant={l.export_status === 'SENT' ? 'success' : 'danger'}>
                              {l.export_status === 'SENT' ? 'Sent' : l.export_status === 'FAILED' ? 'Failed' : 'Conflict'}
                            </Badge>
                          </span>
                        ) : <span className="text-ink-subtle">—</span>
                      ) : locked ? (
                        <span className="text-caption text-ink-subtle">Locked</span>
                      ) : editable ? (
                        <div className="flex items-center gap-0.5 whitespace-nowrap">
                          {l.decision && (
                            <Badge variant={l.decision === 'REJECTED' ? 'danger' : 'warning'}>
                              {l.decision === 'OVERRIDDEN' ? 'Changed' : l.decision === 'REJECTED' ? 'Held back' : 'OK'}
                            </Badge>
                          )}
                          <Button size="sm" variant="ghost" onClick={() => startEdit(l)}>Change</Button>
                          {l.decision !== 'REJECTED' && l.qty_allocated > 0 && (
                            <Button size="sm" variant="ghost" disabled={review.isPending} onClick={() => send(l, { decision: 'REJECTED' })}>Hold</Button>
                          )}
                          {(l.decision === 'OVERRIDDEN' || l.decision === 'REJECTED') && (
                            <Button size="sm" variant="ghost" disabled={review.isPending} onClick={() => send(l, { decision: 'APPROVED' })}>Reset</Button>
                          )}
                        </div>
                      ) : null}
                    </TD>
                  </TR>

                  {editing === l.order_id && (
                    <tr className="border-b border-surface-line bg-surface-muted">
                      <td colSpan={10} className="px-3 py-2.5">
                        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
                          e.preventDefault();
                          send(l, { decision: 'OVERRIDDEN', override_qty: Number(qty), override_reason: reason }, () => setEditing(null));
                        }}>
                          <label className="text-label text-ink-muted">
                            Units to send (max {fmt(l.qty_ordered)})
                            <Input type="number" min={0} max={l.qty_ordered} step="any" value={qty} onChange={(e) => setQty(e.target.value)}
                              className="mt-1 h-comp-sm w-28" required />
                          </label>
                          <label className="grow text-label text-ink-muted">
                            Why
                            <Input value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 h-comp-sm"
                              placeholder="Reason for changing the recommendation" required />
                          </label>
                          <Button type="submit" size="sm" disabled={review.isPending || !reason.trim()}>Save</Button>
                          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                        </form>
                      </td>
                    </tr>
                  )}

                  {(l.override_reason || (l.export_error && l.export_status !== 'SENT')) && (
                    <tr className="border-b border-surface-line">
                      <td colSpan={10} className="px-3 pb-1.5 text-caption text-ink-muted">
                        {l.override_reason && <>Reason: {l.override_reason}. </>}
                        {l.export_error && l.export_status !== 'SENT' && <span className="text-danger-text">WMS: {l.export_error}</span>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {lines.length === 0 && (
              <Empty colSpan={10}>
                {filter === 'attention' ? 'No order needs attention. Every one is fully covered.' : 'No order matches these filters.'}
              </Empty>
            )}
          </tbody>
        </Table>
        {shown < lines.length && (
          <div className="border-t border-surface-line px-3 py-2 text-center">
            <Button variant="ghost" size="sm" onClick={() => setShown((n) => n + 60)}>Show more ({lines.length - shown} left)</Button>
          </div>
        )}
      </TableFrame>
    </div>
  );
}
