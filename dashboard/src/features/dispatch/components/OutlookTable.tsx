'use client';

import { Badge } from '@/components/ui/badge';
import { errorMessage } from '@/lib/api';
import { useOutlook } from '../hooks';
import { fmt } from './format';

const LABEL = { OK: 'OK', LOW_COVER: 'Low cover', WILL_STOCK_OUT: 'Will run out', STOCKED_OUT: 'Empty after plan' } as const;
const VARIANT = { OK: 'success', LOW_COVER: 'warning', WILL_STOCK_OUT: 'danger', STOCKED_OUT: 'danger' } as const;
const ORDER = { STOCKED_OUT: 0, WILL_STOCK_OUT: 1, LOW_COVER: 2, OK: 3 } as const;

export function OutlookTable({ planId }: { planId: number }) {
  const q = useOutlook(planId);
  if (q.isLoading) return <p className="py-6 text-ink-muted">Combining the plan with the demand forecast…</p>;
  if (q.isError) return <p role="alert" className="py-6 text-danger-text">{errorMessage(q.error)}</p>;
  const rows = [...(q.data ?? [])].sort((a, b) => ORDER[a.outlook] - ORDER[b.outlook]);
  if (!rows.length) return <p className="py-6 text-ink-muted">No dispatches in this plan yet.</p>;
  return (
    <div className="overflow-x-auto">
      <p className="mb-3 text-body-sm text-ink-muted">
        Stock left after this plan, compared with the next {rows[0].forecast_days} days of forecast demand. Nothing is assumed to arrive.
      </p>
      <table className="w-full text-body-sm">
        <thead><tr className="text-left text-label text-ink-muted border-b border-surface-line">
          <th className="py-2 pr-3">SKU / warehouse</th><th className="pr-3 text-right">On hand</th><th className="pr-3 text-right">Dispatching</th>
          <th className="pr-3 text-right">Left after plan</th><th className="pr-3 text-right">Forecast demand</th><th className="pr-3 text-right">Days of cover</th><th>Outlook</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.product_id}-${r.warehouse_id}`} className="border-b border-surface-line">
              <td className="py-2 pr-3">#{r.product_id} <span className="text-ink-subtle">{r.warehouse_id}</span></td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.stock_on_hand)}</td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.planned_dispatch)}</td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.stock_after_plan)}</td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.forecast_demand, 1)}</td>
              <td className="pr-3 text-right tabular-nums">{fmt(r.days_of_cover, 1)}</td>
              <td><Badge variant={VARIANT[r.outlook]}>{LABEL[r.outlook]}</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
