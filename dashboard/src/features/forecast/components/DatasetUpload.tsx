'use client';

import { useEffect, useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/api';
import { useDatasetActions, useDatasetStatus } from '../hooks';

const n = (v: number | undefined) => (v ?? 0).toLocaleString();

/** Admin only: add new sales data (including new SKUs) and retrain on the old and new data together. */
export function DatasetUpload() {
  const status = useDatasetStatus(true);
  const act = useDatasetActions();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const s = status.data;
  const p = s?.preview;
  const state = s?.state ?? 'idle';
  const err = act.check.error ?? act.apply.error ?? act.retrain.error ?? act.discard.error;

  const pick = (f?: File) => {
    if (f) act.check.mutate(f);
    if (input.current) input.current.value = '';
  };
  const finished = state === 'done' && !!s?.result;
  useEffect(() => {
    if (finished) act.refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  return (
    <section className="rounded-md border border-surface-line bg-surface">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-line px-4 py-2.5">
        <div className="min-w-0 flex-1 basis-96">
          <h2 className="text-h3 text-ink-heading">Sales data and model</h2>
          <p className="text-caption text-ink-muted">
            Add new sales rows, including new SKUs. The model retrains on the data it already has plus yours, so new SKUs become forecastable.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? 'Hide' : 'Upload data'}</Button>
      </header>
      {(open || state === 'running' || state === 'done' || state === 'rejected' || state === 'failed') && (
        <div className="space-y-3 p-4">
          {(state === 'idle' || state === 'ready') && (
            <div className="flex flex-wrap items-center gap-3">
              <input ref={input} type="file" accept=".csv,.xlsx" className="sr-only" id="dataset-file" onChange={(e) => pick(e.target.files?.[0])} />
              <Button size="sm" onClick={() => input.current?.click()} disabled={act.check.isPending}>
                <Upload className="mr-1.5 h-4 w-4" aria-hidden="true" />{act.check.isPending ? 'Checking…' : 'Choose a CSV or Excel file'}
              </Button>
              <Button size="sm" variant="outline" onClick={() => act.retrain.mutate(false)} disabled={act.retrain.isPending}>
                {act.retrain.isPending ? 'Starting…' : 'Retrain on current history'}
              </Button>
              <p className="w-full text-caption text-ink-muted">
                Needs: product_id, warehouse_id, date, units_sold, stock_on_hand, price, category, city. Optional: product_name, discount_pct, promotion_flag,
                is_organic, shelf_life_days, weight_g, event_name_1, event_type_1. Retraining on the current history uses sales already received from the ERP,
                with no file needed.
              </p>
            </div>
          )}

          {p && (state === 'idle' || state === 'ready') && (
            <div className="rounded-md border border-surface-line bg-surface-muted p-3 text-body-sm">
              <p className="font-mono text-caption font-medium text-ink-heading">{p.filename}</p>
              {p.errors.length > 0 && (
                <ul role="alert" className="mt-2 list-disc pl-5 text-danger-text">{p.errors.map((e) => <li key={e}>{e}</li>)}</ul>
              )}
              {p.errors.length === 0 && (
                <>
                  <p className="mt-1 text-ink-body">
                    {n(p.rows)} rows, {p.date_from} to {p.date_to}, {n(p.skus)} SKU-warehouse series. Current data runs to {p.current_history_to}.
                    {(p.overlap_rows ?? 0) > 0 && ` ${n(p.overlap_rows)} rows repeat days already held; the new values replace them.`}
                  </p>
                  <p className="mt-1">
                    {(p.new_product_ids?.length ?? 0) > 0
                      ? <Badge variant="success">New SKUs: {p.new_product_ids!.join(', ')}</Badge>
                      : <span className="text-ink-muted">No new SKUs, the existing ones get more history.</span>}
                  </p>
                  {p.warnings.length > 0 && <ul className="mt-2 list-disc pl-5 text-warning-text">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => act.apply.mutate(false)} disabled={act.apply.isPending}>Retrain on old and new data</Button>
                    <Button size="sm" variant="outline" onClick={() => act.discard.mutate()}>Cancel</Button>
                  </div>
                  <p className="mt-2 text-caption text-ink-muted">Takes a few minutes. The current model keeps working until the new one is ready and has been checked.</p>
                </>
              )}
            </div>
          )}

          {state === 'running' && (
            <div aria-live="polite">
              <p className="text-body-sm font-medium text-ink-heading">{s?.step || 'Working'}…</p>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-pill bg-surface-subtle" role="progressbar" aria-valuenow={s?.progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full rounded-pill bg-primary transition-all" style={{ width: `${s?.progress ?? 5}%` }} />
              </div>
              <p className="mt-2 text-caption text-ink-muted">You can leave this page; the retrain keeps running.</p>
            </div>
          )}

          {finished && s?.result && (
            <div className="rounded-md border border-success-border bg-success-soft p-3 text-body-sm text-success-text">
              <p className="font-semibold">The model now knows {n(s.result.products)} products and data up to {s.result.history_to}.</p>
              <p className="mt-1">
                Error on the most recent {s.result.comparison.holdout_days} days: {s.result.comparison.wape_before === null ? 'not measured' : `${(s.result.comparison.wape_before * 100).toFixed(1)}%`} before, {(s.result.comparison.wape_after * 100).toFixed(1)}% after.
                {s.result.left_out > 0 && ` ${s.result.left_out} series with too little history were left out.`}
              </p>
              <p className="mt-1">Forecasts, units to order and the dispatch plan are being refreshed. Accuracy figures still come from the last full backtest.</p>
              <Button size="sm" variant="outline" className="mt-3" onClick={() => act.discard.mutate()}>Done</Button>
            </div>
          )}

          {state === 'rejected' && s?.result && (
            <div role="alert" className="rounded-md border border-warning-border bg-warning-soft p-3 text-body-sm text-warning-text">
              <p className="font-semibold">The current model was kept.</p>
              <p className="mt-1">
                The new model was {Math.abs(s.result.comparison.change_pct).toFixed(0)}% less accurate on the most recent {s.result.comparison.holdout_days} days
                ({s.result.comparison.wape_before === null ? 'not measured' : `${(s.result.comparison.wape_before * 100).toFixed(1)}%`} before, {(s.result.comparison.wape_after * 100).toFixed(1)}% after). Check the data, or use it anyway.
              </p>
              {s.result.comparison.history_is_sample && (
                <p className="mt-1">
                  The sales history here is the 120-day sample that comes with the project, while the model in use was trained on three years, so a model
                  trained on the sample is expected to score lower. Add the full history file to compare like with like.
                </p>
              )}
              <div className="mt-3 flex gap-2">
                {s.kind === 'history' ? (
                  <Button size="sm" onClick={() => act.retrain.mutate(true)} disabled={act.retrain.isPending}>Use the new model anyway</Button>
                ) : (
                  <Button size="sm" onClick={() => act.apply.mutate(true)} disabled={act.apply.isPending}>Use the new data anyway</Button>
                )}
                <Button size="sm" variant="outline" onClick={() => act.discard.mutate()}>Discard</Button>
              </div>
            </div>
          )}

          {state === 'failed' && (
            <div role="alert" className="rounded-md border border-danger-border bg-danger-soft p-3 text-body-sm text-danger-text">
              <p className="font-semibold">The retrain did not finish. The current model is unchanged.</p>
              <p className="mt-1">{s?.error}</p>
              <Button size="sm" variant="outline" className="mt-3" onClick={() => act.discard.mutate()}>Close</Button>
            </div>
          )}

          {err && <p role="alert" className="text-body-sm text-danger-text">{errorMessage(err)}</p>}
        </div>
      )}
    </section>
  );
}
