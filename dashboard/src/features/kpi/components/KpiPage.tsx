'use client';

import { useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ReportButtons } from '@/features/forecast/components/ReportButtons';
import { errorMessage } from '@/lib/api';
import { useAccuracy } from '../hooks';
import type { Accuracy } from '../types';

const PREDICTED = '#1F4B8E';
const ACTUAL = '#0E8F72';
const TARGET = '#B54708';
const GRID = '#E4E7EC';
const AXIS = '#667085';

const n0 = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const n1 = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const signed = (n: number) => `${n > 0 ? '+' : ''}${n1(n)}%`;
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

export function KpiPage() {
  const q = useAccuracy();

  if (q.isLoading) return <Shell><p className="py-16 text-center text-ink-muted">Loading forecast accuracy…</p></Shell>;
  if (q.isError || !q.data) {
    return <Shell><Card><CardContent role="alert" className="py-10 text-center text-danger-text">{errorMessage(q.error)}</CardContent></Card></Shell>;
  }
  const d = q.data;
  const k = d.kpis;
  const meets = k.day_mape_pct <= d.target_mape_pct;
  const bias = k.day_bias_pct;

  return (
    <Shell>
      <header className="flex flex-wrap items-start justify-between gap-4">
       <div className="max-w-3xl">
        <h1 className="text-[1.5rem] font-semibold tracking-tight text-ink-heading">Forecast accuracy</h1>
        <p className="mt-1 text-body text-ink-muted">
          How closely predicted demand followed what was really sold, from {day(d.period.start)} to {day(d.period.end)} across {k.skus} SKUs{d.warehouse_id ? ` at ${d.warehouse_id}` : ''}.
        </p>
       </div>
       <ReportButtons kind="accuracy" pdfLabel="Accuracy report (PDF)" xlsxLabel="Accuracy data (Excel)" />
      </header>

      <section aria-label="Key figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Daily forecast error" value={`${n1(k.day_mape_pct)}%`}
          badge={<Badge variant={meets ? 'success' : 'danger'}>{meets ? `Within the ${d.target_mape_pct}% target` : `Above the ${d.target_mape_pct}% target`}</Badge>}
          hint="Average gap between predicted and actual units, per SKU per day (MAPE)." />
        <Stat label="Weighted error" value={`${n1(k.day_wape * 100)}%`}
          hint="Total units missed divided by total units sold (WAPE). Big sellers count more." />
        <Stat label="7-day SKU error" value={`${n1(k.sku_week_mape_pct)}%`}
          hint="Error when a week of demand is added up per SKU, the level used for planning." />
        <Stat label="Over or under forecast" value={signed(bias)}
          badge={<Badge variant="secondary">{Math.abs(bias) < 3 ? 'Well balanced' : bias < 0 ? 'Under-forecasts' : 'Over-forecasts'}</Badge>}
          hint={`${n0(k.total_predicted)} units predicted against ${n0(k.total_actual)} sold.`} />
      </section>

      <DemandChart data={d} />

      <MoreDetail data={d} />

      <p className="text-caption text-ink-subtle max-w-3xl">
        Measured by forecasting past weeks the model had not seen, not from live dispatches.
      </p>
    </Shell>
  );
}

type Detail = 'horizon' | 'warehouse' | 'sku';

function MoreDetail({ data }: { data: Accuracy }) {
  const [open, setOpen] = useState<Detail | null>(null);
  const first = data.by_horizon[0];
  const last = data.by_horizon[data.by_horizon.length - 1];
  const buttons: { id: Detail; label: string; ask: string; show: boolean }[] = [
    { id: 'horizon', label: 'Error by forecast day', ask: 'Does accuracy drop for later days?', show: data.by_horizon.length > 1 },
    { id: 'warehouse', label: 'By warehouse', ask: 'Which warehouse is hardest to forecast?', show: data.by_warehouse.length > 1 },
    { id: 'sku', label: 'SKUs to watch', ask: 'Which products are missed the most?', show: data.by_sku.length > 0 },
  ];
  return (
    <section aria-label="More detail" className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body-sm text-ink-muted">More detail:</span>
        {buttons.filter((b) => b.show).map((b) => (
          <Button key={b.id} size="sm" variant={open === b.id ? 'default' : 'outline'} aria-expanded={open === b.id} title={b.ask}
            onClick={() => setOpen(open === b.id ? null : b.id)}>{b.label}</Button>
        ))}
      </div>
      {open === 'horizon' && (
        <>
          <p className="max-w-3xl text-body text-ink-body">
            {first && last && `The first day ahead is off by ${n1(first.mape_pct)}% and day ${last.horizon_day} by ${n1(last.mape_pct)}%. ${last.mape_pct - first.mape_pct > 3 ? 'Trust the next few days most and re-check long orders later.' : 'Accuracy holds up across the whole period.'}`}
          </p>
          <HorizonChart data={data} />
        </>
      )}
      {open === 'warehouse' && <WarehouseDetail data={data} />}
      {open === 'sku' && <SkuDetail data={data} />}
    </section>
  );
}

function WarehouseDetail({ data }: { data: Accuracy }) {
  const sorted = [...data.by_warehouse].sort((a, b) => b.mape_pct - a.mape_pct);
  const hardest = sorted[0];
  const easiest = sorted[sorted.length - 1];
  return (
    <>
      <p className="max-w-3xl text-body text-ink-body">
        {hardest.warehouse_id} is the hardest to forecast ({n1(hardest.mape_pct)}% error) and {easiest.warehouse_id} the easiest ({n1(easiest.mape_pct)}%).
      </p>
      <WarehouseTable data={data} />
    </>
  );
}

function SkuDetail({ data }: { data: Accuracy }) {
  const scored = data.by_sku.filter((r) => r.mean_abs_err_pct !== null);
  const good = scored.filter((r) => (r.mean_abs_err_pct ?? 0) <= 10).length;
  return (
    <>
      <p className="max-w-3xl text-body text-ink-body">
        {good} of {scored.length} SKUs are within 10% over a typical week. The table starts with the largest misses; those are the ones to double-check before ordering.
      </p>
      <SkuTable data={data} />
    </>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">{children}</div>;
}

function Stat({ label, value, badge, hint }: { label: string; value: string; badge?: React.ReactNode; hint: string }) {
  return (
    <div className="rounded-xl border border-surface-line bg-surface p-5 shadow-card">
      <p className="text-body-sm text-ink-muted">{label}</p>
      <p className="mt-1 text-[1.875rem] font-semibold leading-none tracking-tight tabular-nums text-ink-heading">{value}</p>
      <div className="mt-2 min-h-6">{badge}</div>
      <p className="mt-1 text-caption text-ink-muted">{hint}</p>
    </div>
  );
}

function DemandChart({ data }: { data: Accuracy }) {
  const [pick, setWh] = useState('');
  const warehouses = Object.keys(data.daily_by_warehouse).sort();
  const onlyOne = warehouses.length === 1;           // a planner's report is already cut to their warehouse
  const wh = onlyOne ? warehouses[0] : pick;
  const series = wh ? data.daily_by_warehouse[wh] : data.daily;
  const rows = useMemo(() => series.map((p) => ({ ...p, label: day(p.date) })), [series]);
  const total = useMemo(() => ({
    p: series.reduce((a, r) => a + r.predicted, 0), a: series.reduce((a, r) => a + r.actual, 0),
  }), [series]);
  const first = new Set(rows.map((r) => r.date));
  const cutoffs = data.origins.map((o) => {
    const next = new Date(`${o}T00:00:00`); next.setDate(next.getDate() + 1);
    return next.toISOString().slice(0, 10);
  }).filter((c) => first.has(c));

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Predicted vs actual daily demand</CardTitle>
          <CardDescription>
            Units per day{wh ? ` at ${wh}` : ', all warehouses'}. Predicted {n0(total.p)} against actual {n0(total.a)}
            {' '}({signed((total.p - total.a) / total.a * 100)}).
          </CardDescription>
        </div>
        {!onlyOne && (
          <label className="text-label text-ink-muted">Warehouse
            <select value={wh} onChange={(e) => setWh(e.target.value)}
              className="ml-2 h-8 rounded-md border border-input bg-surface px-2 text-body-sm text-ink-body">
              <option value="">All warehouses</option>
              {warehouses.map((w) => <option key={w}>{w}</option>)}
            </select>
          </label>
        )}
      </CardHeader>
      <CardContent>
        <div role="img" aria-label="Line chart of predicted and actual daily demand" className="h-[340px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 12 }} tickLine={false} axisLine={{ stroke: GRID }} interval="preserveStartEnd" minTickGap={28} />
              <YAxis tick={{ fill: AXIS, fontSize: 12 }} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => n0(v)} />
              <Tooltip content={<DemandTip />} />
              <Legend verticalAlign="top" align="right" height={28} iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              {cutoffs.map((c) => (
                <ReferenceLine key={c} x={day(c)} stroke="#98A2B3" strokeDasharray="3 3" />
              ))}
              <Line type="monotone" dataKey="actual" name="Actual" stroke={ACTUAL} strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} />
              <Line type="monotone" dataKey="predicted" name="Predicted" stroke={PREDICTED} strokeWidth={2.25} strokeDasharray="6 4" dot={false} activeDot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-caption text-ink-subtle">Dashed vertical lines mark the days the model was retrained and started a new 14-day forecast.</p>
      </CardContent>
    </Card>
  );
}

function DemandTip({ active, payload, label }: { active?: boolean; payload?: { payload: { predicted: number; actual: number } }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const gap = p.predicted - p.actual;
  return (
    <div className="rounded-lg border border-surface-line bg-surface px-3 py-2 text-body-sm shadow-elevated">
      <p className="font-semibold text-ink-heading">{label}</p>
      <p style={{ color: ACTUAL }}>Actual {n0(p.actual)}</p>
      <p style={{ color: PREDICTED }}>Predicted {n0(p.predicted)}</p>
      <p className="text-ink-muted">Gap {gap > 0 ? '+' : ''}{n0(gap)} ({signed(gap / p.actual * 100)})</p>
    </div>
  );
}

function HorizonChart({ data }: { data: Accuracy }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Error by forecast day</CardTitle>
        <CardDescription>How the daily error changes the further ahead the forecast looks.</CardDescription>
      </CardHeader>
      <CardContent>
        <div role="img" aria-label="Bar chart of forecast error by number of days ahead" className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.by_horizon} margin={{ top: 12, right: 12, bottom: 16, left: 0 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="horizon_day" tick={{ fill: AXIS, fontSize: 12 }} tickLine={false} axisLine={{ stroke: GRID }}
                label={{ value: 'Days ahead', position: 'insideBottom', offset: -8, fill: AXIS, fontSize: 12 }} />
              <YAxis tick={{ fill: AXIS, fontSize: 12 }} tickLine={false} axisLine={false} width={44} unit="%" domain={[0, 25]} ticks={[0, 5, 10, 15, 20, 25]} />
              <Tooltip formatter={(v: number) => [`${n1(v)}%`, 'Error']} labelFormatter={(l) => `Day ${l} ahead`} cursor={{ fill: '#F2F4F7' }} />
              <ReferenceLine y={data.target_mape_pct} stroke={TARGET} strokeDasharray="4 4"
                label={{ value: `Target ${data.target_mape_pct}%`, position: 'top', fill: TARGET, fontSize: 12 }} />
              <Bar dataKey="mape_pct" name="Error" fill={PREDICTED} radius={[3, 3, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function WarehouseTable({ data }: { data: Accuracy }) {
  const rows = [...data.by_warehouse].sort((a, b) => a.mape_pct - b.mape_pct);
  const max = Math.max(...rows.map((r) => r.mape_pct), data.target_mape_pct) * 1.25;
  return (
    <Card>
      <CardHeader>
        <CardTitle>By warehouse</CardTitle>
        <CardDescription>Daily error and whether the warehouse was over or under forecast.</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full text-body-sm">
          <thead><tr className="border-b border-surface-line text-left text-label text-ink-muted">
            <th className="py-2 pr-3 font-medium">Warehouse</th><th className="pr-3 font-medium">Daily error</th>
            <th className="pr-3 text-right font-medium">Predicted</th><th className="pr-3 text-right font-medium">Actual</th><th className="text-right font-medium">Bias</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.warehouse_id} className="border-b border-surface-line last:border-0">
                <td className="py-2.5 pr-3 font-medium text-ink-heading">{r.warehouse_id}</td>
                <td className="pr-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-pill bg-surface-subtle" aria-hidden="true">
                      <div className="h-full rounded-pill" style={{ width: `${r.mape_pct / max * 80}%`, background: r.mape_pct <= data.target_mape_pct ? PREDICTED : TARGET }} />
                    </div>
                    <span className="tabular-nums">{n1(r.mape_pct)}%</span>
                  </div>
                </td>
                <td className="pr-3 text-right tabular-nums">{n0(r.predicted)}</td>
                <td className="pr-3 text-right tabular-nums">{n0(r.actual)}</td>
                <td className="text-right tabular-nums">{signed(r.bias_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

type Sort = 'worst' | 'under' | 'over' | 'best';
const SORTS: Record<Sort, string> = {
  worst: 'Largest error first', under: 'Most under-forecast', over: 'Most over-forecast', best: 'Smallest error first',
};
const PAGE = 15;

function SkuTable({ data }: { data: Accuracy }) {
  const [sort, setSort] = useState<Sort>('worst');
  const [search, setSearch] = useState('');
  const [shown, setShown] = useState(PAGE);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = data.by_sku.filter((r) => r.mean_abs_err_pct !== null && (!q || `${r.product_id} ${r.product_name ?? ''} ${r.warehouse_id}`.toLowerCase().includes(q)));
    const key: Record<Sort, (r: Accuracy['by_sku'][number]) => number> = {
      worst: (r) => -(r.mean_abs_err_pct ?? 0), best: (r) => r.mean_abs_err_pct ?? 0,
      under: (r) => r.bias_pct ?? 0, over: (r) => -(r.bias_pct ?? 0),
    };
    return [...list].sort((a, b) => key[sort](a) - key[sort](b));
  }, [data.by_sku, sort, search]);

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>SKU accuracy</CardTitle>
          <CardDescription>Forecast against actual for a typical 7-day period, per SKU. {rows.length} SKUs.</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Search SKU or warehouse" placeholder="Search SKU or warehouse" value={search}
            onChange={(e) => { setSearch(e.target.value); setShown(PAGE); }} className="h-8 w-52" />
          <select aria-label="Sort SKUs" value={sort} onChange={(e) => { setSort(e.target.value as Sort); setShown(PAGE); }}
            className="h-8 rounded-md border border-input bg-surface px-2 text-body-sm text-ink-body">
            {(Object.keys(SORTS) as Sort[]).map((s) => <option key={s} value={s}>{SORTS[s]}</option>)}
          </select>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-body-sm">
            <thead><tr className="border-b border-surface-line text-left text-label text-ink-muted">
              <th className="py-2 pr-3 font-medium">SKU</th><th className="pr-3 font-medium">Warehouse</th>
              <th className="pr-3 text-right font-medium">Predicted (7 days)</th><th className="pr-3 text-right font-medium">Actual (7 days)</th>
              <th className="pr-3 text-right font-medium">Error</th><th className="text-right font-medium">Bias</th>
            </tr></thead>
            <tbody>
              {rows.slice(0, shown).map((r) => (
                <tr key={`${r.product_id}-${r.warehouse_id}`} className="border-b border-surface-line last:border-0">
                  <td className="py-2 pr-3 font-medium text-ink-heading">{r.product_name ?? `SKU ${r.product_id}`} <span className="text-ink-subtle">#{r.product_id}</span></td>
                  <td className="pr-3 text-ink-body">{r.warehouse_id}</td>
                  <td className="pr-3 text-right tabular-nums">{n0(r.forecast_7d)}</td>
                  <td className="pr-3 text-right tabular-nums">{n0(r.actual_7d)}</td>
                  <td className="pr-3 text-right tabular-nums">{n1(r.mean_abs_err_pct ?? 0)}%</td>
                  <td className={`text-right tabular-nums ${Math.abs(r.bias_pct ?? 0) > 15 ? 'text-warning-text' : 'text-ink-body'}`}>{signed(r.bias_pct ?? 0)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="py-8 text-center text-ink-muted">No SKUs match.</td></tr>}
            </tbody>
          </table>
        </div>
        {shown < rows.length && (
          <div className="mt-4 flex justify-center">
            <Button variant="outline" size="sm" onClick={() => setShown((s) => s + PAGE * 2)}>Show more ({rows.length - shown} left)</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
