'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { useCan } from '@/features/auth/store';
import { useCreatePurchase } from '@/features/integrations/hooks';
import { errorMessage } from '@/lib/api';
import { useOrders } from '../hooks';
import type { OrderRow } from '../types';
import { ReportButtons } from './ReportButtons';

const fmt = (n: number | null | undefined, d = 0) => (n === null || n === undefined ? '-' : n.toLocaleString(undefined, { maximumFractionDigits: d }));
const PERIODS = [7, 14, 28];
const PAGE = 25;
const TONE: Record<OrderRow['priority'], 'danger' | 'warning' | 'secondary'> = {
  'Order now': 'danger', 'Order soon': 'warning', 'Plan ahead': 'secondary', Covered: 'secondary',
};

export function OrdersPanel({ warehouse }: { warehouse: string }) {
  const [days, setDays] = useState(7);
  const [safety, setSafety] = useState(true);
  const [shown, setShown] = useState(PAGE);
  const [only, setOnly] = useState<'all' | 'urgent'>('all');
  const q = useOrders(days, safety, warehouse);
  const can = useCan();
  const buy = useCreatePurchase();
  const [confirm, setConfirm] = useState(false);
  const [urgentOnly, setUrgentOnly] = useState(false);

  const rows = useMemo(() => {
    const list = q.data?.rows ?? [];
    return only === 'urgent' ? list.filter((r) => r.priority !== 'Plan ahead') : list;
  }, [q.data, only]);
  const s = q.data?.summary;

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="flex flex-wrap items-end justify-between gap-4 pt-6">
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <p className="mb-1.5 text-label text-ink-muted">Cover demand for the next</p>
              <div role="group" aria-label="Planning period" className="inline-flex overflow-hidden rounded-lg border border-input">
                {PERIODS.map((p) => (
                  <button key={p} type="button" aria-pressed={days === p} onClick={() => { setDays(p); setShown(PAGE); }}
                    className={`h-comp-md px-4 text-body-sm ${days === p ? 'bg-primary text-primary-foreground' : 'bg-surface text-ink-body hover:bg-surface-subtle'}`}>
                    {p} days
                  </button>
                ))}
              </div>
            </div>
            <label className="flex items-start gap-2 text-body-sm text-ink-body">
              <input type="checkbox" checked={safety} onChange={(e) => setSafety(e.target.checked)} className="mt-1 h-4 w-4 accent-[#1F4B8E]" />
              <span>
                Add a safety buffer
                <span className="block text-caption text-ink-muted">Plan for the busy end of the likely range, so a good week does not empty the shelf.</span>
              </span>
            </label>
          </div>
          <ReportButtons kind="orders" days={days} safety={safety} warehouse={warehouse} pdfLabel="Order report (PDF)" xlsxLabel="Order list (Excel)" />
        </CardContent>
      </Card>

      {can.edit && q.data && q.data.summary.units_to_order > 0 && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
            {!confirm && !buy.data && (
              <>
                <p className="text-body-sm text-ink-body">Ready to buy? Send this list to the ERP as purchase orders, one per warehouse.</p>
                <Button onClick={() => setConfirm(true)}>Create purchase order</Button>
              </>
            )}
            {confirm && !buy.data && (
              <>
                <div className="space-y-1.5 text-body-sm text-ink-body">
                  <p>
                    Send {urgentOnly ? fmt(q.data.summary.order_now + q.data.summary.order_soon) : fmt(q.data.summary.skus_to_order)} lines
                    {urgentOnly ? '' : ` (${fmt(q.data.summary.units_to_order)} units)`} for the next {days} days{safety ? ' with the safety buffer' : ''} to the ERP?
                  </p>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={urgentOnly} onChange={(e) => setUrgentOnly(e.target.checked)} className="h-4 w-4 accent-[#1F4B8E]" />
                    Only the urgent ones (Order now and Order soon)
                  </label>
                </div>
                <div className="flex gap-2">
                  <Button disabled={buy.isPending} onClick={() => buy.mutate({ days, safety, warehouse_id: warehouse || undefined, urgent_only: urgentOnly })}>
                    {buy.isPending ? 'Sending…' : 'Send to ERP'}
                  </Button>
                  <Button variant="outline" onClick={() => setConfirm(false)}>Cancel</Button>
                </div>
              </>
            )}
            {buy.data && (
              <div role="status" className="space-y-1 text-body-sm">
                <p className="font-semibold text-ink-heading">
                  {buy.data.filter((p) => p.status === 'SENT').length} of {buy.data.length} purchase orders sent to the ERP.
                </p>
                <p className="text-ink-muted">{buy.data.map((p) => `${p.po_ref} (${fmt(p.total_units)} units, ${p.status === 'SENT' ? 'sent' : 'not sent'})`).join('; ')}</p>
                <p><Link href="/integrations" className="text-primary underline underline-offset-2">See purchase orders</Link>
                  <button type="button" className="ml-4 text-ink-muted underline underline-offset-2" onClick={() => { buy.reset(); setConfirm(false); }}>Done</button></p>
              </div>
            )}
            {buy.isError && <p role="alert" className="w-full text-body-sm text-danger-text">{errorMessage(buy.error)}</p>}
          </CardContent>
        </Card>
      )}

      {q.isLoading && <Card><CardContent className="py-10 text-center text-ink-muted">Working out what to order… the first time can take up to a minute.</CardContent></Card>}
      {q.isError && <Card><CardContent role="alert" className="py-8 text-center text-danger-text">{errorMessage(q.error)}</CardContent></Card>}

      {q.data && s && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Tile label="Units to order" value={fmt(s.units_to_order)} sub={`across ${fmt(s.skus_to_order)} of ${fmt(s.skus_checked)} SKU lines`} />
            <Tile label="Order now" value={fmt(s.order_now)} sub="out of stock or under 3 days of cover" tone="danger" />
            <Tile label="Order soon" value={fmt(s.order_soon)} sub="under a week of cover" tone="warning" />
            <Tile label={`Forecast, next ${days} days`} value={fmt(s.forecast_units)} sub="units expected to sell" />
          </div>

          <Card>
            <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>What to order</CardTitle>
                <CardDescription>
                  Units to order = forecast for {days} days{safety ? ' (with safety buffer)' : ''}, minus stock that is free to sell. Stock already promised to
                  approved orders is not counted as free. Most urgent first.
                </CardDescription>
              </div>
              <div className="flex gap-2" role="group" aria-label="Which lines">
                <Button size="sm" variant={only === 'all' ? 'default' : 'outline'} onClick={() => setOnly('all')}>All ({q.data.rows.length})</Button>
                <Button size="sm" variant={only === 'urgent' ? 'default' : 'outline'} onClick={() => setOnly('urgent')}>Urgent only ({s.order_now + s.order_soon})</Button>
              </div>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-body-sm">
                <thead>
                  <tr className="border-b border-surface-line text-left text-label text-ink-muted">
                    <th className="py-2 pr-4">Priority</th><th className="pr-4">Product</th><th className="pr-4">Warehouse</th>
                    <th className="pr-4 text-right">Order</th><th className="pr-4 text-right">Free stock</th><th className="pr-4 text-right">Forecast</th><th className="text-right">Cover (days)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, shown).map((r) => (
                    <tr key={`${r.product_id}-${r.warehouse_id}`} className="border-b border-surface-line">
                      <td className="py-2 pr-4"><Badge variant={TONE[r.priority]}>{r.priority}</Badge></td>
                      <td className="pr-4"><span className="font-medium text-ink-heading">{r.product_name}</span> <span className="text-ink-subtle">#{r.product_id}</span></td>
                      <td className="pr-4">{r.warehouse_id} <span className="text-ink-subtle">{r.city}</span></td>
                      <td className="pr-4 text-right font-semibold tabular-nums text-ink-heading">{fmt(r.units_to_order)}</td>
                      <td className="pr-4 text-right tabular-nums">{fmt(r.available)}</td>
                      <td className="pr-4 text-right tabular-nums text-ink-muted">{fmt(safety ? r.forecast_high : r.forecast_units)}</td>
                      <td className="text-right tabular-nums">{fmt(r.days_of_cover, 1)}</td>
                    </tr>
                  ))}
                  {rows.length === 0 && <tr><td colSpan={7} className="py-8 text-center text-ink-muted">Nothing to order for this period. Stock covers the forecast.</td></tr>}
                </tbody>
              </table>
              {shown < rows.length && (
                <div className="pt-4 text-center">
                  <Button variant="outline" size="sm" onClick={() => setShown((n) => n + PAGE)}>Show more ({rows.length - shown} left)</Button>
                </div>
              )}
              <p className="mt-4 text-caption text-ink-subtle">Based on sales data up to {q.data.history_to}. Stock is the latest figure in that data.</p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: 'danger' | 'warning' }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-label text-ink-muted">{label}</p>
        <p className={`text-h1 tabular-nums ${tone === 'danger' ? 'text-danger-text' : tone === 'warning' ? 'text-warning-text' : 'text-ink-heading'}`}>{value}</p>
        <p className="text-caption text-ink-subtle">{sub}</p>
      </CardContent>
    </Card>
  );
}
