'use client';

import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Notice, Section } from '@/components/ui/section';
import { errorMessage } from '@/lib/api';
import { useServiceKpis } from '../hooks';

const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

/** Delivery against the service-level target, day by day, for the last 30 days. Only days something was approved or
 *  shipped have a point. */
export function ServiceTrend() {
  const q = useServiceKpis();
  const rows = (q.data?.trend ?? []).map((t) => ({ ...t, label: day(t.date) }));
  const target = q.data?.service_level.target_pct;

  return (
    <Section title="Delivery trend" lead="Units sent of those asked for in each approved plan, and orders shipped by their due date.">
      {q.isError && <Notice>{errorMessage(q.error)}</Notice>}
      {!q.isError && rows.length === 0 && (
        <p className="rounded-md border border-surface-line bg-surface px-4 py-6 text-center text-body-sm text-ink-muted">
          {q.isLoading ? 'Loading…' : 'Nothing has been approved or shipped in the last 30 days.'}
        </p>
      )}
      {rows.length > 0 && (
        <div role="img" aria-label="Line chart of fill rate and on-time share by day"
          className="h-[200px] w-full rounded-md border border-surface-line bg-surface p-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#E2E6ED" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#5A6782', fontSize: 11 }} tickLine={false} axisLine={{ stroke: '#E2E6ED' }} interval="preserveStartEnd" minTickGap={28} />
              <YAxis domain={[0, 100]} tick={{ fill: '#5A6782', fontSize: 11 }} tickLine={false} axisLine={false} width={40} tickFormatter={(v: number) => `${v}%`} />
              <Tooltip formatter={(v: number) => `${v}%`} />
              <Legend verticalAlign="top" align="right" height={24} iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              {target !== undefined && <ReferenceLine y={target} stroke="#B4690E" strokeDasharray="4 4" />}
              <Line type="monotone" dataKey="fill_rate_pct" name="Fill rate" stroke="#1F4B8E" strokeWidth={2} connectNulls dot={{ r: 2 }} />
              <Line type="monotone" dataKey="on_time_pct" name="Shipped on time" stroke="#0E7C5A" strokeWidth={2} connectNulls dot={{ r: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Section>
  );
}
