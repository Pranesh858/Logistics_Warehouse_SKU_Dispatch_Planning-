'use client';

import { SidePanel } from '@/components/ui/panel';
import { errorMessage } from '@/lib/api';
import { useExplain } from '../hooks';

const n = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d });

/** Why this SKU is forecast the way it is: recent sales against the forecast, and what moved it. */
export function ExplainPanel({ product_id, warehouse_id, days, onClose }: {
  product_id: number; warehouse_id: string; days: number; onClose: () => void;
}) {
  const q = useExplain(product_id, warehouse_id, days);
  const d = q.data;

  return (
    <SidePanel title={`SKU ${product_id}`} subtitle={d ? `${d.warehouse_id} · ${d.city}` : warehouse_id} onClose={onClose}>
      {q.isLoading && <p className="text-body-sm text-ink-muted">Working out what drives this SKU…</p>}
      {q.isError && <p role="alert" className="text-body-sm text-danger-text">{errorMessage(q.error)}</p>}

      {d && (
        <>
          <p className="text-body-sm text-ink-body">
            <span className="tabular text-metric text-ink-heading">{n(d.total_predicted_units, 1)}</span>
            <span className="ml-1.5">units over {d.days} days</span>
          </p>
          <p className="text-caption text-ink-muted">Likely {n(d.total_range_80pct[0])} to {n(d.total_range_80pct[1])}.</p>

          <h3 className="mb-2 mt-5 text-h4 text-ink-heading">Day by day</h3>
          <Chart data={d} />
          <p className="mt-1.5 text-caption text-ink-muted">
            Grey is what really sold. Blue is the forecast, with its likely range behind it.
          </p>

          <h3 className="mb-2 mt-5 text-h4 text-ink-heading">What moves it</h3>
          <ul className="divide-y divide-surface-line">
            {d.forecast[0]?.drivers.map((dr) => (
              <li key={dr.driver} className="flex items-start justify-between gap-3 py-1.5 text-body-sm">
                <span className="text-ink-body">{dr.reason}</span>
                <span className={`tabular shrink-0 font-medium ${dr.factor >= 1 ? 'text-success-text' : 'text-danger-text'}`}>
                  ×{dr.factor.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-caption text-ink-muted">
            Above 1 pushes this SKU above a typical one, below 1 pulls it down. For {d.forecast[0]?.date}.
          </p>
        </>
      )}
    </SidePanel>
  );
}

function Chart({ data }: { data: NonNullable<ReturnType<typeof useExplain>['data']> }) {
  const past = data.recent_actuals.slice(-7);
  const max = Math.max(1, ...data.forecast.map((f) => f.range_80pct[1] || f.predicted_units), ...past.map((a) => a.units_sold));
  const h = (v: number) => `${Math.max(2, (v / max) * 100)}%`;

  return (
    <div className="flex h-32 items-end gap-1" role="img" aria-label="Recent sales and forecast per day">
      {past.map((a) => (
        <Column key={a.date} label={a.date.slice(5)} title={`${a.date}: ${n(a.units_sold, 1)} sold`}>
          <div className="w-full rounded-sm bg-ink-subtle" style={{ height: h(a.units_sold) }} />
        </Column>
      ))}
      {data.forecast.map((f) => (
        <Column key={f.date} label={f.date.slice(5)} title={`${f.date}: ${n(f.predicted_units, 1)} forecast`}>
          <div className="absolute bottom-0 w-full rounded-sm bg-primary/20" style={{ height: h(f.range_80pct[1]) }} />
          <div className="relative w-full rounded-sm bg-primary" style={{ height: h(f.predicted_units) }} />
        </Column>
      ))}
    </div>
  );
}

function Column({ label, title, children }: { label: string; title: string; children: React.ReactNode }) {
  return (
    <div className="flex h-full min-w-0 flex-1 flex-col justify-end" title={title}>
      <div className="relative flex w-full flex-1 items-end">{children}</div>
      <span className="mt-1 truncate text-center text-micro text-ink-subtle">{label}</span>
    </div>
  );
}
