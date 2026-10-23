'use client';

import { useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice } from '@/components/ui/section';
import { Empty, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { ReportButtons } from '@/features/forecast/components/ReportButtons';
import { errorMessage } from '@/lib/api';
import { useAccuracy } from '../hooks';
import type { Accuracy } from '../types';

const PREDICTED = '#1F4B8E';
const ACTUAL = '#0E7C5A';
const TARGET = '#B4690E';
const GRID = '#E2E6ED';
const AXIS = '#5A6782';

const n0 = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 });
const n1 = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const signed = (n: number) => `${n > 0 ? '+' : ''}${n1(n)}%`;
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

/** How close the forecast has been. One chart by default; the rest behind buttons, each with its reading. */
export function KpiPage() {
  const q = useAccuracy();

  if (q.isLoading) {
    return (<><PageHeader title="Forecast accuracy" /><PageBody><p className="py-16 text-center text-body-sm text-ink-muted">Loading…</p></PageBody></>);
  }
  if (q.isError || !q.data) {
    return (<><PageHeader title="Forecast accuracy" /><PageBody><Notice>{errorMessage(q.error)}</Notice></PageBody></>);
  }

  const d = q.data;
  const k = d.kpis;
  const meets = k.day_mape_pct <= d.target_mape_pct;

  return (
    <>
      <PageHeader
        title="Forecast accuracy"
        lead={`${day(d.period.start)} to ${day(d.period.end)}, ${k.skus} SKUs${d.warehouse_id ? ` at ${d.warehouse_id}` : ''}, measured on weeks the model had not seen`}
        actions={<ReportButtons kind="accuracy" pdfLabel="Summary" xlsxLabel="Full data" />}
      />
      <PageBody className="space-y-4">
        <MetricBand>
          <Metric label="Daily error" value={`${n1(k.day_mape_pct)}%`} tone={meets ? 'good' : 'bad'}
            note={meets ? `within the ${d.target_mape_pct}% target` : `above the ${d.target_mape_pct}% target`} />
          <Metric label="Weighted error" value={`${n1(k.day_wape * 100)}%`} note="big sellers count more" />
          <Metric label="Weekly SKU error" value={`${n1(k.sku_week_mape_pct)}%`} note="the level used for planning" />
          <Metric label="Over or under" value={signed(k.day_bias_pct)}
            note={`${n0(k.total_predicted)} forecast vs ${n0(k.total_actual)} sold`}
            tone={Math.abs(k.day_bias_pct) < 3 ? 'neutral' : 'warn'} />
        </MetricBand>

        <DemandChart data={d} />
        <MoreDetail data={d} />
      </PageBody>
    </>
  );
}

function Panel({ title, lead, right, children }: {
  title: string; lead?: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="rounded-md border border-surface-line bg-surface">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-line px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-h3 text-ink-heading">{title}</h2>
          {lead && <p className="text-caption text-ink-muted">{lead}</p>}
        </div>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

function DemandChart({ data }: { data: Accuracy }) {
  const [pick, setWh] = useState('');
  const warehouses = Object.keys(data.daily_by_warehouse).sort();
  const onlyOne = warehouses.length === 1;
  const wh = onlyOne ? warehouses[0] : pick;
  const series = wh ? data.daily_by_warehouse[wh] : data.daily;
  const rows = useMemo(() => series.map((p) => ({ ...p, label: day(p.date) })), [series]);
  const total = useMemo(
    () => ({ p: series.reduce((a, r) => a + r.predicted, 0), a: series.reduce((a, r) => a + r.actual, 0) }),
    [series],
  );
  const dates = new Set(rows.map((r) => r.date));
  const cutoffs = data.origins
    .map((o) => { const next = new Date(`${o}T00:00:00`); next.setDate(next.getDate() + 1); return next.toISOString().slice(0, 10); })
    .filter((c) => dates.has(c));

  return (
    <Panel
      title="Predicted against actual"
      lead={`Units per day${wh ? ` at ${wh}` : ', all warehouses'}. ${n0(total.p)} predicted, ${n0(total.a)} sold (${signed((total.p - total.a) / total.a * 100)}).`}
      right={!onlyOne && (
        <label className="flex items-center gap-1.5 text-label text-ink-muted">
          Warehouse
          <select value={wh} onChange={(e) => setWh(e.target.value)}
            className="h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
            <option value="">All</option>
            {warehouses.map((w) => <option key={w}>{w}</option>)}
          </select>
        </label>
      )}
    >
      <div role="img" aria-label="Line chart of predicted and actual daily demand" className="h-[300px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID }} interval="preserveStartEnd" minTickGap={28} />
            <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={52} tickFormatter={(v: number) => n0(v)} />
            <Tooltip content={<DemandTip />} />
            <Legend verticalAlign="top" align="right" height={24} iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            {cutoffs.map((c) => <ReferenceLine key={c} x={day(c)} stroke="#9AA6BC" strokeDasharray="3 3" />)}
            <Line type="monotone" dataKey="actual" name="Actual" stroke={ACTUAL} strokeWidth={2} dot={false} activeDot={{ r: 3 }} />
            <Line type="monotone" dataKey="predicted" name="Predicted" stroke={PREDICTED} strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1.5 text-caption text-ink-subtle">Dashed verticals mark where the model was retrained and started a new {data.horizon_days}-day forecast.</p>
    </Panel>
  );
}

function DemandTip({ active, payload, label }: { active?: boolean; payload?: { payload: { predicted: number; actual: number } }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const gap = p.predicted - p.actual;
  return (
    <div className="rounded-md border border-surface-rule bg-surface px-2.5 py-1.5 text-caption shadow-pop">
      <p className="font-medium text-ink-heading">{label}</p>
      <p style={{ color: ACTUAL }}>Actual {n0(p.actual)}</p>
      <p style={{ color: PREDICTED }}>Predicted {n0(p.predicted)}</p>
      <p className="text-ink-muted">Gap {gap > 0 ? '+' : ''}{n0(gap)} ({signed(gap / p.actual * 100)})</p>
    </div>
  );
}

type Detail = 'horizon' | 'warehouse' | 'sku';

function MoreDetail({ data }: { data: Accuracy }) {
  const [open, setOpen] = useState<Detail | null>(null);
  const buttons: { id: Detail; label: string; show: boolean }[] = [
    { id: 'horizon', label: 'Error by forecast day', show: data.by_horizon.length > 1 },
    { id: 'warehouse', label: 'By warehouse', show: data.by_warehouse.length > 1 },
    { id: 'sku', label: 'SKUs to watch', show: data.by_sku.length > 0 },
  ];

  return (
    <section aria-label="More detail" className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-caption text-ink-muted">More detail</span>
        {buttons.filter((b) => b.show).map((b) => (
          <Button key={b.id} size="sm" variant={open === b.id ? 'default' : 'outline'} aria-expanded={open === b.id}
            onClick={() => setOpen(open === b.id ? null : b.id)}>{b.label}</Button>
        ))}
      </div>
      {open === 'horizon' && <HorizonDetail data={data} />}
      {open === 'warehouse' && <WarehouseDetail data={data} />}
      {open === 'sku' && <SkuDetail data={data} />}
    </section>
  );
}

function HorizonDetail({ data }: { data: Accuracy }) {
  const first = data.by_horizon[0];
  const last = data.by_horizon[data.by_horizon.length - 1];
  const drift = last.mape_pct - first.mape_pct;
  return (
    <Panel
      title="Error by forecast day"
      lead={`Day one is off by ${n1(first.mape_pct)}%, day ${last.horizon_day} by ${n1(last.mape_pct)}%. ${
        drift > 3 ? 'Trust the first few days most, and re-check longer orders later.' : 'Accuracy holds across the whole period.'}`}
    >
      <div role="img" aria-label="Bar chart of forecast error by days ahead" className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.by_horizon} margin={{ top: 8, right: 8, bottom: 16, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="horizon_day" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID }}
              label={{ value: 'Days ahead', position: 'insideBottom', offset: -8, fill: AXIS, fontSize: 11 }} />
            <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} unit="%" domain={[0, 25]} ticks={[0, 5, 10, 15, 20, 25]} />
            <Tooltip formatter={(v: number) => [`${n1(v)}%`, 'Error']} labelFormatter={(l) => `Day ${l} ahead`} cursor={{ fill: '#F1F3F7' }} />
            <ReferenceLine y={data.target_mape_pct} stroke={TARGET} strokeDasharray="4 4"
              label={{ value: `Target ${data.target_mape_pct}%`, position: 'top', fill: TARGET, fontSize: 11 }} />
            <Bar dataKey="mape_pct" name="Error" fill={PREDICTED} radius={[2, 2, 0, 0]} maxBarSize={26} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

function WarehouseDetail({ data }: { data: Accuracy }) {
  const rows = [...data.by_warehouse].sort((a, b) => b.mape_pct - a.mape_pct);
  const max = Math.max(...rows.map((r) => r.mape_pct), data.target_mape_pct) * 1.25;
  const worst = rows[0];
  const best = rows[rows.length - 1];
  return (
    <Panel title="By warehouse"
      lead={`${worst.warehouse_id} is hardest to forecast at ${n1(worst.mape_pct)}%; ${best.warehouse_id} is easiest at ${n1(best.mape_pct)}%.`}>
      <TableFrame>
        <Table>
          <THead>
            <tr><TH>Warehouse</TH><TH>Daily error</TH><TH align="right">Predicted</TH><TH align="right">Actual</TH><TH align="right">Bias</TH></tr>
          </THead>
          <tbody>
            {rows.map((r) => (
              <TR key={r.warehouse_id} rail={r.mape_pct > data.target_mape_pct ? 'warn' : 'none'}>
                <TD strong>{r.warehouse_id}</TD>
                <TD>
                  <span className="flex items-center gap-2">
                    <span className="h-1 w-24 overflow-hidden rounded-pill bg-surface-subtle" aria-hidden="true">
                      <span className="block h-full rounded-pill"
                        style={{ width: `${r.mape_pct / max * 80}%`, background: r.mape_pct <= data.target_mape_pct ? PREDICTED : TARGET }} />
                    </span>
                    <span className="tabular">{n1(r.mape_pct)}%</span>
                  </span>
                </TD>
                <TD align="right">{n0(r.predicted)}</TD>
                <TD align="right">{n0(r.actual)}</TD>
                <TD align="right" muted>{signed(r.bias_pct)}</TD>
              </TR>
            ))}
          </tbody>
        </Table>
      </TableFrame>
    </Panel>
  );
}

type Sort = 'worst' | 'under' | 'over' | 'best';
const SORTS: Record<Sort, string> = {
  worst: 'Largest miss first', under: 'Most under-forecast', over: 'Most over-forecast', best: 'Smallest miss first',
};
const PAGE = 15;

function SkuDetail({ data }: { data: Accuracy }) {
  const [sort, setSort] = useState<Sort>('worst');
  const [search, setSearch] = useState('');
  const [shown, setShown] = useState(PAGE);

  const scored = useMemo(() => data.by_sku.filter((r) => r.mean_abs_err_pct !== null), [data.by_sku]);
  const good = scored.filter((r) => (r.mean_abs_err_pct ?? 0) <= 10).length;

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = scored.filter((r) => !q || `${r.product_id} ${r.product_name ?? ''} ${r.warehouse_id}`.toLowerCase().includes(q));
    const key: Record<Sort, (r: Accuracy['by_sku'][number]) => number> = {
      worst: (r) => -(r.mean_abs_err_pct ?? 0), best: (r) => r.mean_abs_err_pct ?? 0,
      under: (r) => r.bias_pct ?? 0, over: (r) => -(r.bias_pct ?? 0),
    };
    return [...list].sort((a, b) => key[sort](a) - key[sort](b));
  }, [scored, sort, search]);

  return (
    <Panel
      title="SKUs to watch"
      lead={`${good} of ${scored.length} SKUs land within 10% over a typical week. The largest misses are the ones to check before ordering.`}
      right={
        <div className="flex items-center gap-1.5">
          <input aria-label="Find a SKU" placeholder="Find a SKU" value={search}
            onChange={(e) => { setSearch(e.target.value); setShown(PAGE); }}
            className="h-comp-sm w-40 rounded-md border border-input bg-surface px-2 text-caption text-ink-heading placeholder:text-ink-subtle hover:border-ink-subtle" />
          <select aria-label="Sort SKUs" value={sort} onChange={(e) => { setSort(e.target.value as Sort); setShown(PAGE); }}
            className="h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
            {(Object.keys(SORTS) as Sort[]).map((s) => <option key={s} value={s}>{SORTS[s]}</option>)}
          </select>
        </div>
      }
    >
      <TableFrame>
        <Table>
          <THead>
            <tr>
              <TH>Product</TH><TH>Warehouse</TH><TH align="right">Predicted</TH>
              <TH align="right">Actual</TH><TH align="right">Miss</TH><TH align="right">Bias</TH>
            </tr>
          </THead>
          <tbody>
            {rows.slice(0, shown).map((r) => (
              <TR key={`${r.product_id}-${r.warehouse_id}`} rail={(r.mean_abs_err_pct ?? 0) > 20 ? 'warn' : 'none'}>
                <TD strong className="max-w-[20rem] truncate">
                  {r.product_name ?? `SKU ${r.product_id}`} <span className="font-mono text-caption text-ink-subtle">#{r.product_id}</span>
                </TD>
                <TD muted>{r.warehouse_id}</TD>
                <TD align="right">{n0(r.forecast_7d)}</TD>
                <TD align="right">{n0(r.actual_7d)}</TD>
                <TD align="right">{n1(r.mean_abs_err_pct ?? 0)}%</TD>
                <TD align="right" className={Math.abs(r.bias_pct ?? 0) > 15 ? 'text-warning-text' : 'text-ink-muted'}>{signed(r.bias_pct ?? 0)}</TD>
              </TR>
            ))}
            {rows.length === 0 && <Empty colSpan={6}>No SKU matches that.</Empty>}
          </tbody>
        </Table>
        {shown < rows.length && (
          <div className="border-t border-surface-line px-3 py-2 text-center">
            <Button variant="ghost" size="sm" onClick={() => setShown((s) => s + PAGE * 2)}>Show more ({rows.length - shown} left)</Button>
          </div>
        )}
      </TableFrame>
    </Panel>
  );
}
