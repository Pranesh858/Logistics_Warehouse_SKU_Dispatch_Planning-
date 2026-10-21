'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { errorMessage } from '@/lib/api';
import { useExplain } from '../hooks';

export function ExplainPanel({ product_id, warehouse_id, days }: { product_id: number; warehouse_id: string; days: number }) {
  const q = useExplain(product_id, warehouse_id, days);

  if (q.isLoading) return <Card><CardContent className="py-8 text-ink-muted">Working out what drives SKU #{product_id}…</CardContent></Card>;
  if (q.isError || !q.data) return <Card><CardContent role="alert" className="py-8 text-danger-text">{errorMessage(q.error)}</CardContent></Card>;

  const d = q.data;
  const max = Math.max(1, ...d.forecast.map((f) => f.range_80pct[1] || f.predicted_units), ...d.recent_actuals.map((a) => a.units_sold));
  const first = d.forecast[0];

  return (
    <Card>
      <CardHeader>
        <CardTitle>SKU #{d.product_id} at {d.warehouse_id} ({d.city})</CardTitle>
        <CardDescription>
          Expected {d.total_predicted_units.toLocaleString(undefined, { maximumFractionDigits: 1 })} units over {d.days} days
          (likely {d.total_range_80pct[0]?.toLocaleString()} to {d.total_range_80pct[1]?.toLocaleString()}).
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-8 lg:grid-cols-2">
        <div>
          <h4 className="text-h4 text-ink-heading mb-3">Day by day</h4>
          <div className="flex items-end gap-1.5 h-40" role="img" aria-label="Recent sales and forecast per day">
            {d.recent_actuals.slice(-7).map((a) => (
              <Bar key={a.date} label={a.date.slice(5)} value={a.units_sold} max={max} tone="past" />
            ))}
            {d.forecast.map((f) => (
              <Bar key={f.date} label={f.date.slice(5)} value={f.predicted_units} max={max} tone="future"
                low={f.range_80pct[0]} high={f.range_80pct[1]} />
            ))}
          </div>
          <p className="mt-2 text-caption text-ink-muted">Grey: recent actual sales. Blue: forecast, with the 80% range as the lighter bar.</p>
        </div>
        <div>
          <h4 className="text-h4 text-ink-heading mb-3">Why the first day looks like this ({first?.date})</h4>
          <ul className="space-y-2">
            {first?.drivers.map((dr) => (
              <li key={dr.driver} className="flex items-start justify-between gap-4 text-body-sm">
                <span>{dr.reason}</span>
                <span className={`tabular-nums font-semibold ${dr.factor >= 1 ? 'text-success-text' : 'text-danger-text'}`}>
                  {dr.factor >= 1 ? '↑' : '↓'} x{dr.factor.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-caption text-ink-muted">
            A factor above 1 raises the forecast above a typical SKU; below 1 lowers it. Factors multiply to the forecast.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function Bar({ label, value, max, tone, low, high }: { label: string; value: number; max: number; tone: 'past' | 'future'; low?: number; high?: number }) {
  const h = (v: number) => `${Math.max(2, (v / max) * 100)}%`;
  return (
    <div className="flex-1 h-full flex flex-col justify-end items-center min-w-0" title={`${label}: ${value.toFixed(1)}`}>
      <div className="relative w-full flex-1 flex items-end">
        {high !== undefined && low !== undefined && (
          <div className="absolute bottom-0 w-full rounded-sm bg-primary/20" style={{ height: h(high) }} />
        )}
        <div className={`relative w-full rounded-sm ${tone === 'past' ? 'bg-ink-subtle' : 'bg-primary'}`} style={{ height: h(value) }} />
      </div>
      <span className="mt-1 text-[10px] text-ink-muted">{label}</span>
    </div>
  );
}
