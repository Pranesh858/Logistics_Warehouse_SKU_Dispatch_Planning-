'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCan } from '@/features/auth/store';
import { errorMessage } from '@/lib/api';
import { useRunForecast, useSkus } from '../hooks';
import type { ForecastTotal } from '../types';
import { DatasetUpload } from './DatasetUpload';
import { ExplainPanel } from './ExplainPanel';
import { OrdersPanel } from './OrdersPanel';
import { ReportButtons } from './ReportButtons';

const fmt = (n: number | null | undefined, d = 0) =>
  n === null || n === undefined ? '-' : n.toLocaleString(undefined, { maximumFractionDigits: d });

const PAGE = 25;

export function ForecastPage() {
  const can = useCan();
  const [tab, setTab] = useState<'forecast' | 'orders'>('forecast');
  const skus = useSkus();
  const run = useRunForecast();

  const [days, setDays] = useState(7);
  const [warehouse, setWarehouse] = useState('');
  const [product, setProduct] = useState('');
  const [shown, setShown] = useState(PAGE);
  const [selected, setSelected] = useState<{ product_id: number; warehouse_id: string } | null>(null);

  const warehouses = useMemo(() => Array.from(new Set((skus.data ?? []).map((s) => s.warehouse_id))).sort(), [skus.data]);
  const stock = useMemo(() => {
    const m = new Map<string, number>();
    (skus.data ?? []).forEach((s) => m.set(`${s.product_id}|${s.warehouse_id}`, s.stock_on_hand));
    return m;
  }, [skus.data]);

  const submit = () => {
    setShown(PAGE);
    setSelected(null);
    run.mutate({
      days,
      product_ids: product.trim() ? product.split(',').map((p) => Number(p.trim())).filter((n) => Number.isFinite(n)) : undefined,
      warehouse_ids: warehouse ? [warehouse] : undefined,
    });
  };

  const reportDays = (run.data?.days ?? days) > 14 ? 28 : (run.data?.days ?? days) > 7 ? 14 : 7;   // reports come in 7, 14 or 28 days

  const rows: ForecastTotal[] = useMemo(
    () => [...(run.data?.totals ?? [])].sort((a, b) => b.total_predicted_units - a.total_predicted_units),
    [run.data],
  );

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      <header>
        <h1 className="text-[1.5rem] font-semibold tracking-tight text-ink-heading">Demand forecast</h1>
        <p className="text-body text-ink-muted max-w-2xl">
          How many units of each SKU every warehouse is expected to sell over the next few days, with a likely range.
          Dispatch planning has its own page; the two meet only in its stock outlook.
        </p>
      </header>

      {can.admin && <DatasetUpload />}

      <div role="tablist" aria-label="Forecast views" className="inline-flex overflow-hidden rounded-lg border border-input">
        {([['forecast', 'Demand forecast'], ['orders', 'Units to order']] as const).map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`h-comp-md px-5 text-body-sm font-medium ${tab === id ? 'bg-primary text-primary-foreground' : 'bg-surface text-ink-body hover:bg-surface-subtle'}`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'orders' && (
        <>
          {warehouses.length > 1 && (
            <label className="flex items-center gap-2 text-label text-ink-muted">Warehouse
              <select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className="h-9 rounded-md border border-input bg-surface px-2 text-body-sm text-ink-body">
                <option value="">All warehouses</option>
                {warehouses.map((w) => <option key={w} value={w}>{w}</option>)}
              </select>
            </label>
          )}
          <OrdersPanel warehouse={warehouse} />
        </>
      )}

      {tab === 'forecast' && (<>

      <Card>
        <CardContent className="pt-6">
          <form
            className="flex flex-wrap items-end gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="days" className="block">Days ahead</Label>
              <Input id="days" type="number" min={1} max={28} value={days} className="w-28"
                onChange={(e) => setDays(Math.min(28, Math.max(1, Number(e.target.value) || 1)))} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="wh" className="block">Warehouse</Label>
              <select id="wh" value={warehouse} onChange={(e) => setWarehouse(e.target.value)}
                className="h-comp-md rounded-lg border border-input bg-surface px-3 text-body-sm">
                <option value="">All warehouses</option>
                {warehouses.map((w) => <option key={w} value={w}>{w}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sku" className="block">SKU ids (optional)</Label>
              <Input id="sku" placeholder="e.g. 10, 25, 38" value={product} onChange={(e) => setProduct(e.target.value)} className="w-52" />
            </div>
            <Button type="submit" disabled={run.isPending || skus.isLoading}>
              {run.isPending ? 'Forecasting…' : 'Run forecast'}
            </Button>
          </form>
          {skus.isError && <p role="alert" className="mt-3 text-body-sm text-danger-text">{errorMessage(skus.error)}</p>}
          {run.isError && <p role="alert" className="mt-3 text-body-sm text-danger-text">{errorMessage(run.error)}</p>}
        </CardContent>
      </Card>

      {!run.data && !run.isPending && (
        <Card><CardContent className="py-10 text-center text-ink-muted text-body">
          Choose how far ahead to look and press <strong>Run forecast</strong>. Leave warehouse and SKU empty to forecast the whole catalogue.
        </CardContent></Card>
      )}

      {run.data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-body-sm text-ink-muted">Reports cover the next {reportDays} days{warehouse ? ` at ${warehouse}` : ''}.</p>
            <ReportButtons kind="forecast" days={reportDays} warehouse={warehouse}
              pdfLabel="Forecast report (PDF)" xlsxLabel="Forecast list (Excel)" />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label={`Total demand, next ${run.data.days} days`} value={fmt(run.data.grand_total)} sub="units, selected scope" />
            <Stat label="Typical error, one day ahead" value={`${run.data.model.mape_pct}%`} sub={`WAPE ${run.data.model.wape}, tested on past data`} />
            <Stat label="SKU x warehouse pairs" value={fmt(rows.length)} sub={`${run.data.model.objective} model, ${fmt(run.data.model.training_rows)} training rows`} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Forecast by SKU and warehouse</CardTitle>
              <CardDescription>Highest demand first. Select a row to see what is driving it. The range covers 80% of past outcomes.</CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-body-sm">
                <thead>
                  <tr className="text-left text-label text-ink-muted border-b border-surface-line">
                    <th className="py-2 pr-4">SKU</th><th className="pr-4">Warehouse</th>
                    <th className="pr-4 text-right">Forecast</th><th className="pr-4 text-right">Likely range</th>
                    <th className="pr-4 text-right">On hand</th><th className="text-right">Cover (days)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, shown).map((r) => {
                    const on = stock.get(`${r.product_id}|${r.warehouse_id}`);
                    const perDay = r.total_predicted_units / r.forecast_days;
                    const cover = on !== undefined && perDay > 0 ? on / perDay : null;
                    const active = selected?.product_id === r.product_id && selected.warehouse_id === r.warehouse_id;
                    return (
                      <tr key={`${r.product_id}-${r.warehouse_id}`}
                        className={`border-b border-surface-line cursor-pointer hover:bg-surface-subtle ${active ? 'bg-primary-soft' : ''}`}
                        onClick={() => setSelected({ product_id: r.product_id, warehouse_id: r.warehouse_id })}>
                        <td className="py-2 pr-4 font-medium text-ink-heading">
                          <button type="button" className="underline-offset-2 hover:underline focus-visible:underline"
                            onClick={(e) => { e.stopPropagation(); setSelected({ product_id: r.product_id, warehouse_id: r.warehouse_id }); }}>
                            #{r.product_id}
                          </button>
                        </td>
                        <td className="pr-4">{r.warehouse_id} <span className="text-ink-subtle">{r.city}</span></td>
                        <td className="pr-4 text-right tabular-nums">{fmt(r.total_predicted_units, 1)}</td>
                        <td className="pr-4 text-right tabular-nums text-ink-muted">{fmt(r.total_low, 1)} to {fmt(r.total_high, 1)}</td>
                        <td className="pr-4 text-right tabular-nums">{fmt(on)}</td>
                        <td className="text-right tabular-nums">
                          {cover === null ? '-' : cover < r.forecast_days ? <Badge variant="danger">{fmt(cover, 1)}</Badge> : fmt(cover, 1)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {shown < rows.length && (
                <div className="pt-4 text-center">
                  <Button variant="outline" size="sm" onClick={() => setShown((n) => n + PAGE)}>
                    Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown} remaining
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {selected && <ExplainPanel product_id={selected.product_id} warehouse_id={selected.warehouse_id} days={run.data.days} />}
        </>
      )}
      </>)}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-label text-ink-muted">{label}</p>
        <p className="text-h1 text-ink-heading tabular-nums">{value}</p>
        <p className="text-caption text-ink-subtle">{sub}</p>
      </CardContent>
    </Card>
  );
}
