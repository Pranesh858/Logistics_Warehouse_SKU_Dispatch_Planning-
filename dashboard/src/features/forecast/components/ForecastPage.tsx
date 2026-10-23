'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice } from '@/components/ui/section';
import { Empty, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useCan, useScope } from '@/features/auth/store';
import { errorMessage } from '@/lib/api';
import { useRunForecast, useSkus } from '../hooks';
import type { ForecastTotal } from '../types';
import { DatasetUpload } from './DatasetUpload';
import { ExplainPanel } from './ExplainPanel';
import { ReportButtons } from './ReportButtons';

const n = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d });

const PAGE = 40;

/** What each SKU is expected to sell, with the range around it and what is driving it. */
export function ForecastPage() {
  const can = useCan();
  const scope = useScope();
  const skus = useSkus();
  const run = useRunForecast();

  const [days, setDays] = useState(7);
  const [product, setProduct] = useState('');
  const [shown, setShown] = useState(PAGE);
  const [picked, setPicked] = useState<{ product_id: number; warehouse_id: string } | null>(null);
  const [showData, setShowData] = useState(false);

  const stock = useMemo(() => {
    const m = new Map<string, number>();
    (skus.data ?? []).forEach((s) => m.set(`${s.product_id}|${s.warehouse_id}`, s.stock_on_hand));
    return m;
  }, [skus.data]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    setShown(PAGE);
    setPicked(null);
    run.mutate({
      days,
      product_ids: product.trim()
        ? product.split(',').map((p) => Number(p.trim())).filter((x) => Number.isFinite(x))
        : undefined,
      warehouse_ids: scope ? [scope] : undefined,
    });
  };

  const rows: ForecastTotal[] = useMemo(
    () => [...(run.data?.totals ?? [])].sort((a, b) => b.total_predicted_units - a.total_predicted_units),
    [run.data],
  );
  const reportDays = days > 14 ? 28 : days > 7 ? 14 : 7;
  const short = rows.filter((r) => {
    const on = stock.get(`${r.product_id}|${r.warehouse_id}`);
    return on !== undefined && on < r.total_predicted_units;
  }).length;

  return (
    <>
      <PageHeader
        title="Demand forecast"
        lead={`Expected units per SKU and warehouse${scope ? ` at ${scope}` : ''}, with the range around each one`}
        actions={
          <>
            <WarehouseSwitch />
            {can.admin && (
              <Button variant="outline" size="sm" aria-expanded={showData} onClick={() => setShowData((v) => !v)}>
                {showData ? 'Hide data tools' : 'Data and model'}
              </Button>
            )}
            {run.data && <ReportButtons kind="forecast" days={reportDays} warehouse={scope ?? undefined} pdfLabel="Summary" xlsxLabel="Full list" />}
          </>
        }
      >
        <form className="flex flex-wrap items-center gap-2" onSubmit={submit}>
          <label className="flex items-center gap-1.5 text-label text-ink-muted">
            Days ahead
            <input type="number" min={1} max={28} value={days} onChange={(e) => setDays(Math.min(28, Math.max(1, Number(e.target.value) || 1)))}
              className="h-comp-sm w-16 rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle" />
          </label>
          <label className="flex items-center gap-1.5 text-label text-ink-muted">
            SKU ids
            <input value={product} onChange={(e) => setProduct(e.target.value)} placeholder="all"
              className="h-comp-sm w-40 rounded-md border border-input bg-surface px-2 text-caption text-ink-heading placeholder:text-ink-subtle hover:border-ink-subtle" />
          </label>
          <Button type="submit" size="sm" disabled={run.isPending || skus.isLoading}>
            {run.isPending ? 'Forecasting…' : 'Run forecast'}
          </Button>
          {run.data && <span className="ml-auto text-caption text-ink-subtle">{rows.length} SKU-warehouse lines</span>}
        </form>
      </PageHeader>

      <PageBody className="space-y-4">
        {can.admin && showData && <DatasetUpload />}
        {skus.isError && <Notice>{errorMessage(skus.error)}</Notice>}
        {run.isError && <Notice>{errorMessage(run.error)}</Notice>}

        {!run.data && !run.isPending && (
          <div className="rounded-md border border-dashed border-surface-rule bg-surface px-6 py-12 text-center">
            <p className="text-body text-ink-body">Choose how far ahead to look, then run the forecast.</p>
            <p className="mt-1 text-caption text-ink-muted">Leave SKU ids empty to cover the whole catalogue.</p>
            <Button className="mt-4" size="sm" onClick={() => submit()} disabled={skus.isLoading}>Run forecast</Button>
          </div>
        )}

        {run.data && (
          <>
            <MetricBand>
              <Metric label={`Demand, next ${run.data.days} days`} value={n(run.data.grand_total)} note="units in this scope" />
              <Metric label="Will not cover demand" value={n(short)} note="SKUs with less stock than forecast" tone={short > 0 ? 'warn' : 'neutral'} />
              <Metric label="Typical error" value={`${run.data.model.mape_pct}%`} note={`one day ahead, tested on past sales`} />
              <Metric label="Trained on" value={n(run.data.model.training_rows)} note={`rows, ${run.data.model.objective} model`} />
            </MetricBand>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
              <TableFrame>
                <Table>
                  <THead>
                    <tr>
                      <TH>SKU</TH><TH>Warehouse</TH>
                      <TH align="right">Forecast</TH><TH align="right">Likely range</TH>
                      <TH align="right">On hand</TH><TH align="right">Cover</TH>
                    </tr>
                  </THead>
                  <tbody>
                    {rows.slice(0, shown).map((r) => {
                      const on = stock.get(`${r.product_id}|${r.warehouse_id}`);
                      const perDay = r.total_predicted_units / r.forecast_days;
                      const cover = on !== undefined && perDay > 0 ? on / perDay : null;
                      const tight = cover !== null && cover < r.forecast_days;
                      const active = picked?.product_id === r.product_id && picked?.warehouse_id === r.warehouse_id;
                      return (
                        <TR key={`${r.product_id}-${r.warehouse_id}`} rail={tight ? 'warn' : 'none'} selected={active}
                          onClick={() => setPicked({ product_id: r.product_id, warehouse_id: r.warehouse_id })}>
                          <TD mono strong>#{r.product_id}</TD>
                          <TD className="whitespace-nowrap">{r.warehouse_id} <span className="text-ink-subtle">{r.city}</span></TD>
                          <TD align="right" strong>{n(r.total_predicted_units, 1)}</TD>
                          <TD align="right" muted>{n(r.total_low, 0)} – {n(r.total_high, 0)}</TD>
                          <TD align="right">{n(on)}</TD>
                          <TD align="right" className={tight ? 'text-warning-text' : undefined}>
                            {cover === null ? '—' : `${n(cover, 1)} d`}
                          </TD>
                        </TR>
                      );
                    })}
                    {rows.length === 0 && <Empty colSpan={6}>No SKUs in this scope.</Empty>}
                  </tbody>
                </Table>
                {shown < rows.length && (
                  <div className="border-t border-surface-line px-3 py-2 text-center">
                    <Button variant="ghost" size="sm" onClick={() => setShown((v) => v + PAGE)}>Show more ({rows.length - shown} left)</Button>
                  </div>
                )}
              </TableFrame>

              {picked && (
                <ExplainPanel product_id={picked.product_id} warehouse_id={picked.warehouse_id} days={run.data.days}
                  onClose={() => setPicked(null)} />
              )}
            </div>
            <p className="text-caption text-ink-subtle">
              The range covers 80% of past outcomes at this horizon. Select a row to see what is driving its forecast.
            </p>
          </>
        )}
      </PageBody>
    </>
  );
}
