'use client';

import Link from 'next/link';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice, Section } from '@/components/ui/section';
import { errorMessage } from '@/lib/api';
import { useAccuracy, useServiceKpis } from '../hooks';

const rate = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`);

/** How well orders are being served, next to how well demand is being predicted. A rate with nothing behind it shows
 *  a dash: no shipments yet is not an on-time share of 0%. */
export function ServiceKpiPanel() {
  const q = useServiceKpis();
  const accuracy = useAccuracy();
  const k = q.data;
  const level = k?.service_level;
  const error = accuracy.data?.kpis.day_mape_pct;
  const errorTarget = accuracy.data?.target_mape_pct;

  return (
    <Section title="Service levels"
      lead={level ? `Target ${level.target_pct}% of ordered units planned.${k?.plan_version ? ` Plan v${k.plan_version}.` : ''}` : undefined}
      actions={<Link href="/kpi" className="text-caption font-medium text-primary hover:underline">Trend and accuracy</Link>}>
      {q.isError && <Notice>{errorMessage(q.error)}</Notice>}
      {!q.isError && (
        <MetricBand className="lg:grid-cols-6">
          <Metric label="Fill rate" value={q.isLoading ? '…' : rate(k?.fill_rate_pct)}
            tone={level?.met === true ? 'good' : level?.met === false ? 'bad' : 'neutral'}
            note={level?.met === null || level?.met === undefined ? 'nothing planned' : level.met ? 'meets the target' : 'below the target'} />
          <Metric label="Orders fully planned" value={rate(k?.order_fill_rate_pct)}
            note={k ? `${k.orders_fully_planned.toLocaleString()} of ${k.orders.toLocaleString()}` : undefined} />
          <Metric label="Shipped on time" value={rate(k?.on_time_pct)}
            note={k?.shipped ? `${k.shipped_on_time.toLocaleString()} of ${k.shipped.toLocaleString()} shipped` : 'nothing shipped yet'} />
          <Metric label="Stock-outs" value={k?.stock_outs.toLocaleString() ?? '—'} note="orders with nothing to give"
            tone={k && k.stock_outs > 0 ? 'bad' : 'neutral'} />
          <Metric label="Orders at risk" value={k?.at_risk.toLocaleString() ?? '—'} note="short and due soon"
            tone={k && k.at_risk > 0 ? 'warn' : 'neutral'} />
          <Metric label="Forecast error" value={rate(error)}
            tone={error === undefined || errorTarget === undefined ? 'neutral' : error <= errorTarget ? 'good' : 'bad'}
            note={errorTarget === undefined ? 'not measured' : `target ${errorTarget}% or less`} />
        </MetricBand>
      )}
    </Section>
  );
}
