'use client';

import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Notice } from '@/components/ui/section';
import { Empty, Table, TableFrame, TD, TH, THead, TR, type Rail } from '@/components/ui/table';
import { errorMessage } from '@/lib/api';
import { useCan } from '@/features/auth/store';
import {
  useApproveTransfer, useCancelTransfer, useReceiveTransfer, useTransfers,
} from '../hooks';
import type { StockTransfer, TransferStatus } from '../types';
import { fmt, fmtDate } from './format';

const STATUS: Record<TransferStatus, { label: string; tone: 'warning' | 'default' | 'success' | 'secondary'; rail: Rail }> = {
  PROPOSED: { label: 'Proposed', tone: 'warning', rail: 'warn' },
  IN_TRANSIT: { label: 'In transit', tone: 'default', rail: 'info' },
  RECEIVED: { label: 'Received', tone: 'success', rail: 'good' },
  CANCELLED: { label: 'Cancelled', tone: 'secondary', rail: 'none' },
};

const OPEN: TransferStatus[] = ['PROPOSED', 'IN_TRANSIT'];

/**
 * Stock the company holds, in the wrong warehouse.
 *
 * Each row is a shortage one warehouse cannot fill and another can. Approving one sends the goods: the
 * donor's stock drops straight away, because that is when they leave the shelf.
 */
export function TransfersTable({ editable }: { editable: boolean }) {
  const { data, isLoading, isError, error } = useTransfers();
  const can = useCan();
  const approve = useApproveTransfer();
  const receive = useReceiveTransfer();
  const cancel = useCancelTransfer();
  const [closing, setClosing] = useState<number | null>(null);
  const [reason, setReason] = useState('');

  if (isLoading) return <p className="py-10 text-center text-body-sm text-ink-muted">Checking other warehouses…</p>;
  if (isError) return <Notice>{errorMessage(error)}</Notice>;

  const rows = data ?? [];
  const open = rows.filter((t) => OPEN.includes(t.status));
  const closed = rows.filter((t) => !OPEN.includes(t.status)).slice(0, 15);
  const busy = approve.isPending || receive.isPending || cancel.isPending;
  const failure = approve.error ?? receive.error ?? cancel.error;

  return (
    <div className="space-y-4">
      {failure && <Notice>{errorMessage(failure)}</Notice>}

      <TableFrame>
        <Table>
          <THead>
            <TR>
              <TH>SKU</TH>
              <TH>Route</TH>
              <TH align="right">Units</TH>
              <TH align="right">Arrives</TH>
              <TH>Why</TH>
              <TH>Status</TH>
              {editable && <TH align="right">Action</TH>}
            </TR>
          </THead>
          <tbody>
            {open.length === 0 && (
              <Empty colSpan={editable ? 7 : 6}>
                Nothing to move. Every shortage in this plan is either covered or has no spare stock elsewhere
                that would arrive in time.
              </Empty>
            )}
            {open.map((t) => (
              <TR key={t.id} rail={t.overdue ? 'bad' : STATUS[t.status].rail}>
                <TD mono strong>{t.product_id}</TD>
                <TD>
                  <span aria-label={`${t.from_warehouse_id} to ${t.to_warehouse_id}`}
                    className="inline-flex items-center gap-1.5 font-medium text-ink-heading">
                    {t.from_warehouse_id}
                    <ArrowRight className="h-3 w-3 text-ink-muted" aria-hidden="true" />
                    {t.to_warehouse_id}
                  </span>
                  <span className="ml-2 text-caption text-ink-muted">
                    {t.transit_days} {t.transit_days === 1 ? 'day' : 'days'}
                  </span>
                </TD>
                <TD align="right" strong>{fmt(t.qty)}</TD>
                <TD align="right" muted={!t.overdue} className={t.overdue ? 'font-medium text-danger-text' : undefined}>
                  {t.eta ? fmtDate(t.eta) : '—'}
                  {t.overdue && <span className="block text-caption">overdue</span>}
                </TD>
                <TD muted className="max-w-md whitespace-normal text-caption">{t.reason}</TD>
                <TD><Badge variant={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge></TD>
                {editable && (
                  <TD align="right">
                    {closing === t.id ? (
                      <form
                        className="flex items-center justify-end gap-1.5"
                        onSubmit={(e) => {
                          e.preventDefault();
                          cancel.mutate({ id: t.id, reason }, { onSuccess: () => { setClosing(null); setReason(''); } });
                        }}
                      >
                        <input
                          autoFocus
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          placeholder="Reason"
                          aria-label={`Why transfer ${t.transfer_ref} is cancelled`}
                          className="w-36 rounded-sm border border-surface-rule bg-surface px-2 py-1 text-caption text-ink-body placeholder:text-ink-muted focus:border-primary focus:outline-none"
                        />
                        <Button size="sm" variant="destructive" type="submit" disabled={busy}>Cancel it</Button>
                        <Button size="sm" variant="ghost" type="button" onClick={() => { setClosing(null); setReason(''); }}>
                          Keep
                        </Button>
                      </form>
                    ) : (
                      <div className="flex items-center justify-end gap-1.5">
                        {t.status === 'PROPOSED' && (
                          <Button size="sm" onClick={() => approve.mutate(t.id)} disabled={busy}>
                            Approve &amp; send
                          </Button>
                        )}
                        {t.status === 'IN_TRANSIT' && (
                          <Button size="sm" variant="outline" onClick={() => receive.mutate(t.id)} disabled={busy}>
                            Mark arrived
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" onClick={() => setClosing(t.id)} disabled={busy}>
                          Cancel
                        </Button>
                      </div>
                    )}
                  </TD>
                )}
              </TR>
            ))}
          </tbody>
        </Table>
      </TableFrame>

      {!can.edit && <Notice tone="info">View only. A planner or admin approves a transfer.</Notice>}

      {closed.length > 0 && (
        <TableFrame>
          <Table>
            <THead>
              <TR>
                <TH>SKU</TH>
                <TH>Route</TH>
                <TH align="right">Units</TH>
                <TH>Outcome</TH>
                <TH>Who</TH>
              </TR>
            </THead>
            <tbody>
              {closed.map((t) => (
                <TR key={t.id}>
                  <TD mono>{t.product_id}</TD>
                  <TD muted>{t.from_warehouse_id} → {t.to_warehouse_id}</TD>
                  <TD align="right">{fmt(t.qty)}</TD>
                  <TD>
                    <Badge variant={STATUS[t.status].tone}>{STATUS[t.status].label}</Badge>
                    {t.cancel_reason && <span className="ml-2 text-caption text-ink-muted">{t.cancel_reason}</span>}
                  </TD>
                  <TD muted className="text-caption">
                    {t.received_by ?? t.cancelled_by ?? t.approved_by ?? '—'}
                    {t.received_at && ` · ${fmtDate(t.received_at)}`}
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        </TableFrame>
      )}
    </div>
  );
}

/** One line for the plan header: is there stock sitting in the wrong place? */
export function transferHint(rows: StockTransfer[] | undefined): string | null {
  const proposed = (rows ?? []).filter((t) => t.status === 'PROPOSED');
  if (!proposed.length) return null;
  const units = proposed.reduce((n, t) => n + t.qty, 0);
  return `${fmt(units)} units could be moved in from ${new Set(proposed.map((t) => t.from_warehouse_id)).size} other warehouse(s).`;
}
