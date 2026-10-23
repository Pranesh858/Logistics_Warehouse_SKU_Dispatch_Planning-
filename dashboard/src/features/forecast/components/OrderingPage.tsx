'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { SidePanel } from '@/components/ui/panel';
import { Facts, Notice } from '@/components/ui/section';
import { Empty, Rail, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useCan, useScope } from '@/features/auth/store';
import { useCreatePurchase } from '@/features/integrations/hooks';
import { errorMessage } from '@/lib/api';
import { useOrders } from '../hooks';
import type { OrderRow } from '../types';
import { ReportButtons } from './ReportButtons';

const n = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d });

const PERIODS = [7, 14, 28];
const PAGE = 40;

const RAIL: Record<OrderRow['priority'], Rail> = {
  'Order now': 'bad', 'Order soon': 'warn', 'Plan ahead': 'none', Covered: 'none',
};
const TONE: Record<OrderRow['priority'], 'danger' | 'warning' | 'secondary'> = {
  'Order now': 'danger', 'Order soon': 'warning', 'Plan ahead': 'secondary', Covered: 'secondary',
};

/** How many units to buy, and how urgent each line is. The planner's buying screen. */
export function OrderingPage() {
  const scope = useScope();
  const can = useCan();
  const [days, setDays] = useState(7);
  const [safety, setSafety] = useState(true);
  const [urgentOnly, setUrgentOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [shown, setShown] = useState(PAGE);
  const [picked, setPicked] = useState<OrderRow | null>(null);
  const [confirm, setConfirm] = useState(false);

  const q = useOrders(days, safety, scope ?? undefined);
  const buy = useCreatePurchase();
  const s = q.data?.summary;

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (q.data?.rows ?? []).filter(
      (r) => (!urgentOnly || r.priority !== 'Plan ahead') &&
        (!term || `${r.product_id} ${r.product_name} ${r.warehouse_id}`.toLowerCase().includes(term)),
    );
  }, [q.data, urgentOnly, search]);

  const change = (fn: () => void) => { fn(); setShown(PAGE); setPicked(null); buy.reset(); setConfirm(false); };

  return (
    <>
      <PageHeader
        title="Ordering"
        lead={`Units to buy to cover the next ${days} days${safety ? ', with a safety buffer' : ''}`}
        actions={<><WarehouseSwitch /><ReportButtons kind="orders" days={days} safety={safety} warehouse={scope ?? undefined}
          pdfLabel="Summary" xlsxLabel="Full list" /></>}
      >
        <div role="group" aria-label="Period" className="inline-flex overflow-hidden rounded-md border border-surface-rule">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={days === p} onClick={() => change(() => setDays(p))}
              className={`h-comp-sm border-r border-surface-rule px-3 text-caption font-medium last:border-0 transition-colors ${
                days === p ? 'bg-primary text-primary-foreground' : 'bg-surface text-ink-body hover:bg-surface-subtle'}`}>
              {p} days
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-caption text-ink-body">
          <input type="checkbox" checked={safety} onChange={(e) => change(() => setSafety(e.target.checked))}
            className="h-3.5 w-3.5 accent-[#1F4B8E]" />
          Safety buffer
        </label>
        <label className="flex items-center gap-1.5 text-caption text-ink-body">
          <input type="checkbox" checked={urgentOnly} onChange={(e) => change(() => setUrgentOnly(e.target.checked))}
            className="h-3.5 w-3.5 accent-[#1F4B8E]" />
          Urgent only
        </label>
        <input value={search} onChange={(e) => { setSearch(e.target.value); setShown(PAGE); }} placeholder="Find a product"
          aria-label="Find a product"
          className="h-comp-sm w-48 rounded-md border border-input bg-surface px-2 text-caption text-ink-heading placeholder:text-ink-subtle hover:border-ink-subtle" />
        <span className="ml-auto text-caption text-ink-subtle">{rows.length} of {q.data?.rows.length ?? 0} lines</span>
      </PageHeader>

      <PageBody className="space-y-4">
        <MetricBand>
          <Metric label="Units to order" value={q.isLoading ? '…' : n(s?.units_to_order)} note={`across ${n(s?.skus_to_order)} lines`} />
          <Metric label="Order now" value={n(s?.order_now)} note="under 3 days of cover" tone={s && s.order_now > 0 ? 'bad' : 'neutral'} />
          <Metric label="Order soon" value={n(s?.order_soon)} note="under a week of cover" tone={s && s.order_soon > 0 ? 'warn' : 'neutral'} />
          <Metric label={`Demand, ${days} days`} value={n(s?.forecast_units)} note={`over ${n(s?.skus_checked)} SKUs`} />
        </MetricBand>

        {q.isError && <Notice>{errorMessage(q.error)}</Notice>}
        {q.isLoading && <Notice tone="info">Working out what to order. The first run of the day can take up to a minute.</Notice>}

        {can.edit && s && s.units_to_order > 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-surface-line bg-surface px-4 py-3">
            {!confirm && !buy.data && (
              <>
                <p className="flex-1 text-body-sm text-ink-body">Send this list to the ERP as purchase orders, one per warehouse.</p>
                <Button size="sm" onClick={() => setConfirm(true)}>Create purchase orders</Button>
              </>
            )}
            {confirm && !buy.data && (
              <>
                <p className="flex-1 text-body-sm text-ink-body">
                  Send {urgentOnly ? `${n(s.order_now + s.order_soon)} urgent lines` : `${n(s.skus_to_order)} lines, ${n(s.units_to_order)} units`} for
                  the next {days} days{safety ? ' with the safety buffer' : ''}?
                </p>
                <Button size="sm" disabled={buy.isPending}
                  onClick={() => buy.mutate({ days, safety, warehouse_id: scope ?? undefined, urgent_only: urgentOnly })}>
                  {buy.isPending ? 'Sending…' : 'Send to ERP'}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setConfirm(false)}>Cancel</Button>
              </>
            )}
            {buy.data && (
              <div role="status" className="flex-1 text-body-sm">
                <p className="font-medium text-ink-heading">
                  {buy.data.filter((p) => p.status === 'SENT').length} of {buy.data.length} purchase orders sent.
                </p>
                <p className="text-caption text-ink-muted">{buy.data.map((p) => `${p.po_ref} · ${n(p.total_units)} units`).join('   ')}</p>
              </div>
            )}
            {buy.data && (
              <>
                <Link href="/integrations" className="text-caption font-medium text-primary hover:underline">See purchase orders</Link>
                <Button size="sm" variant="ghost" onClick={() => { buy.reset(); setConfirm(false); }}>Done</Button>
              </>
            )}
            {buy.isError && <Notice>{errorMessage(buy.error)}</Notice>}
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
          <TableFrame>
            <Table>
              <THead>
                <tr>
                  <TH>Priority</TH><TH>Product</TH><TH>Warehouse</TH>
                  <TH align="right">Order</TH><TH align="right">Free stock</TH>
                  <TH align="right">Demand</TH><TH align="right">Cover</TH>
                </tr>
              </THead>
              <tbody>
                {rows.slice(0, shown).map((r) => (
                  <TR key={`${r.product_id}-${r.warehouse_id}`} rail={RAIL[r.priority]}
                    selected={picked?.product_id === r.product_id && picked?.warehouse_id === r.warehouse_id}
                    onClick={() => setPicked(r)}>
                    <TD><Badge variant={TONE[r.priority]}>{r.priority}</Badge></TD>
                    <TD strong className="max-w-[22rem] truncate">
                      {r.product_name} <span className="font-mono text-caption text-ink-subtle">#{r.product_id}</span>
                    </TD>
                    <TD className="whitespace-nowrap">{r.warehouse_id} <span className="text-ink-subtle">{r.city}</span></TD>
                    <TD align="right" strong>{n(r.units_to_order)}</TD>
                    <TD align="right">{n(r.available)}</TD>
                    <TD align="right" muted>{n(safety ? r.forecast_high : r.forecast_units)}</TD>
                    <TD align="right">{r.days_of_cover === null ? '—' : `${n(r.days_of_cover, 1)} d`}</TD>
                  </TR>
                ))}
                {rows.length === 0 && !q.isLoading && (
                  <Empty colSpan={7}>{search ? 'No product matches that.' : 'Nothing to order for this period. Stock covers the forecast.'}</Empty>
                )}
              </tbody>
            </Table>
            {shown < rows.length && (
              <div className="border-t border-surface-line px-3 py-2 text-center">
                <Button variant="ghost" size="sm" onClick={() => setShown((v) => v + PAGE)}>Show more ({rows.length - shown} left)</Button>
              </div>
            )}
          </TableFrame>

          {picked && (
            <SidePanel title={picked.product_name} subtitle={`SKU ${picked.product_id} · ${picked.warehouse_id}`} onClose={() => setPicked(null)}>
              <Facts rows={[
                ['Order', <strong key="o">{n(picked.units_to_order)} units</strong>],
                ['Priority', <Badge key="p" variant={TONE[picked.priority]}>{picked.priority}</Badge>],
                ['Forecast demand', `${n(picked.forecast_units)} units`],
                ['Busy-week demand', `${n(picked.forecast_high)} units`],
                ['Stock on hand', n(picked.stock_on_hand)],
                ['Held for approved orders', n(picked.reserved)],
                ['Free to sell', n(picked.available)],
                ['Days of cover', picked.days_of_cover === null ? '—' : `${n(picked.days_of_cover, 1)} days`],
                ['Category', picked.category],
              ]} />
              <p className="mt-3 text-caption text-ink-muted">
                Order = {safety ? 'busy-week demand' : 'forecast demand'} over {days} days, less free stock, never below zero.
              </p>
            </SidePanel>
          )}
        </div>

        <p className="text-caption text-ink-subtle">
          Based on sales data up to {q.data?.history_to ?? '—'}. Free stock is what the warehouse reports, less units already promised to approved orders.
        </p>
      </PageBody>
    </>
  );
}
