'use client';

import { Badge } from '@/components/ui/badge';
import { Empty, Rail, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { errorMessage } from '@/lib/api';
import { useOutlook } from '../hooks';
import { fmt } from './format';

const LABEL = { OK: 'OK', LOW_COVER: 'Low cover', WILL_STOCK_OUT: 'Will run out', STOCKED_OUT: 'Empty after plan' } as const;
const VARIANT = { OK: 'success', LOW_COVER: 'warning', WILL_STOCK_OUT: 'danger', STOCKED_OUT: 'danger' } as const;
const ORDER = { STOCKED_OUT: 0, WILL_STOCK_OUT: 1, LOW_COVER: 2, OK: 3 } as const;
const RAIL: Record<keyof typeof LABEL, Rail> = { OK: 'none', LOW_COVER: 'warn', WILL_STOCK_OUT: 'bad', STOCKED_OUT: 'bad' };

export function OutlookTable({ planId }: { planId: number }) {
  const q = useOutlook(planId);
  if (q.isLoading) return <p className="py-6 text-body-sm text-ink-muted">Combining the plan with the demand forecast…</p>;
  if (q.isError) return <p role="alert" className="py-6 text-body-sm text-danger-text">{errorMessage(q.error)}</p>;
  const rows = [...(q.data ?? [])].sort((a, b) => ORDER[a.outlook] - ORDER[b.outlook]);
  if (!rows.length) return <p className="py-6 text-body-sm text-ink-muted">No dispatches in this plan yet.</p>;
  return (
    <div className="space-y-2">
      <p className="text-caption text-ink-muted">
        Stock left after this plan against the next {rows[0].forecast_days} days of forecast demand. Nothing is assumed to arrive.
      </p>
      <TableFrame>
        <Table>
          <THead>
            <tr>
              <TH>SKU</TH><TH>Warehouse</TH><TH align="right">On hand</TH><TH align="right">Dispatching</TH>
              <TH align="right">Left after</TH><TH align="right">Demand</TH><TH align="right">Cover</TH><TH>Outlook</TH>
            </tr>
          </THead>
          <tbody>
            {rows.map((r) => (
              <TR key={`${r.product_id}-${r.warehouse_id}`} rail={RAIL[r.outlook]}>
                <TD mono strong>#{r.product_id}</TD>
                <TD muted>{r.warehouse_id}</TD>
                <TD align="right">{fmt(r.stock_on_hand)}</TD>
                <TD align="right">{fmt(r.planned_dispatch)}</TD>
                <TD align="right" strong>{fmt(r.stock_after_plan)}</TD>
                <TD align="right" muted>{fmt(r.forecast_demand, 1)}</TD>
                <TD align="right">{r.days_of_cover === null ? '\u2014' : `${fmt(r.days_of_cover, 1)} d`}</TD>
                <TD><Badge variant={VARIANT[r.outlook]}>{LABEL[r.outlook]}</Badge></TD>
              </TR>
            ))}
            {rows.length === 0 && <Empty colSpan={8}>Nothing is being dispatched yet.</Empty>}
          </tbody>
        </Table>
      </TableFrame>
    </div>
  );
}
