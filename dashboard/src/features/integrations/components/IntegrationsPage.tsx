'use client';

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice } from '@/components/ui/section';
import { Empty, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { useCan } from '@/features/auth/store';
import { errorMessage } from '@/lib/api';
import { useAudit, useConfirmAll, useIntegrationStatus, usePending, usePurchaseOrders, useReceivePurchase, useRetryPurchase, useSync } from '../hooks';
import type { Feed } from '../types';
import { ConnectionsCard } from './ConnectionsCard';

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Never';

const n = (v: number | null | undefined) => (v ?? 0).toLocaleString();

const WHAT: Record<Feed['feed'], string> = {
  inventory: 'Live stock per SKU and warehouse. Every plan and order list uses it.',
  orders: 'New customer orders. Each one rebuilds the dispatch plan.',
  sales: 'Daily sales added to the history the forecast learns from.',
  purchasing: 'Purchase orders raised from the ordering list, and what has arrived.',
  dispatch: 'Approved orders sent out, and what the warehouse confirms shipped.',
};

const PULLED = new Set(['inventory', 'orders', 'sales']);

type Tab = 'feeds' | 'orders' | 'log';

/** What this planner exchanges with the WMS and ERP, and whether the last exchange worked. */
export function IntegrationsPage() {
  const can = useCan();
  const status = useIntegrationStatus();
  const sync = useSync();
  const po = usePurchaseOrders();
  const retry = useRetryPurchase();
  const receive = useReceivePurchase();
  const pending = usePending();
  const confirmAll = useConfirmAll();
  const [tab, setTab] = useState<Tab>('feeds');
  const [trail, setTrail] = useState(false);
  const audit = useAudit(trail && can.admin);
  const [busy, setBusy] = useState<string | null>(null);

  const run = (feed: 'inventory' | 'orders' | 'sales') => {
    setBusy(feed);
    sync.mutate(feed, { onSettled: () => setBusy(null) });
  };

  const d = status.data;
  const simulated = d ? d.feeds.some((f) => f.mode === 'simulator') : false;
  const broken = (d?.feeds ?? []).filter((f) => f.last?.status === 'FAILED').length;
  const live = (d?.feeds ?? []).filter((f) => f.mode === 'live').length;

  return (
    <>
      <PageHeader
        title="Systems"
        lead="What comes in from the WMS and ERP, what goes out to them, and whether the last exchange worked"
      >
        <div role="tablist" aria-label="Sections" className="flex gap-0.5">
          {([['feeds', 'Connections'], ['orders', 'Purchase orders'], ['log', 'Activity']] as [Tab, string][]).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} type="button" onClick={() => setTab(k)}
              className={`rounded-md px-2.5 py-1 text-caption font-medium transition-colors ${
                tab === k ? 'bg-primary-soft text-primary' : 'text-ink-muted hover:bg-surface-subtle hover:text-ink-heading'}`}>
              {label}
            </button>
          ))}
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {status.isError && <Notice>{errorMessage(status.error)}</Notice>}
        {status.isLoading && <p className="py-10 text-center text-body-sm text-ink-muted">Loading…</p>}

        {d && (
          <>
            <MetricBand>
              <Metric label="Connected systems" value={`${live} of ${d.feeds.length}`} note={simulated ? 'the rest run on simulators' : 'all live'} />
              <Metric label="Failed exchanges" value={n(broken)} note="in the last attempt" tone={broken ? 'bad' : 'neutral'} />
              <Metric label="Awaiting confirmation" value={n(d.awaiting_confirmation)} note="stock still held"
                tone={d.awaiting_confirmation ? 'warn' : 'neutral'}
                action={can.edit && d.awaiting_confirmation > 0 ? (
                  <Button size="sm" variant="outline" disabled={confirmAll.isPending} onClick={() => confirmAll.mutate()}>
                    {confirmAll.isPending ? 'Recording…' : 'Mark all shipped'}
                  </Button>
                ) : undefined} />
              <Metric label="Live stock levels" value={n(d.live_stock_skus)} note={d.webhooks_enabled ? 'webhooks on' : 'webhooks off'} />
            </MetricBand>

            {confirmAll.data && <Notice tone="good">{confirmAll.data.message}</Notice>}
            {confirmAll.isError && <Notice>{errorMessage(confirmAll.error)}</Notice>}
            {sync.isError && <Notice>{errorMessage(sync.error)}</Notice>}
          </>
        )}

        {d && tab === 'feeds' && (
          <>
            {simulated && (
              <Notice tone="warn">
                Some connections run on built-in simulators, so no real system is contacted.{' '}
                {can.admin ? 'Enter your own system below to switch over.' : 'An admin can connect the real systems here.'}
              </Notice>
            )}

            <TableFrame>
              <Table>
                <THead>
                  <tr>
                    <TH>Exchange</TH><TH>System</TH><TH>Mode</TH><TH>Last result</TH>
                    <TH>When</TH><TH>Automatic</TH><TH />
                  </tr>
                </THead>
                <tbody>
                  {d.feeds.map((f) => (
                    <TR key={f.feed} rail={f.last?.status === 'FAILED' ? 'bad' : f.mode === 'live' ? 'good' : 'none'}>
                      <TD strong>
                        {f.label}
                        <span className="block text-caption font-normal text-ink-subtle">{WHAT[f.feed]}</span>
                      </TD>
                      <TD muted>{f.feed === 'purchasing' || f.feed === 'dispatch' ? 'to' : 'from'} {f.system}</TD>
                      <TD><Badge variant={f.mode === 'live' ? 'success' : 'secondary'}>{f.mode === 'live' ? 'Live' : 'Simulator'}</Badge></TD>
                      <TD className="max-w-[26rem]">
                        {f.last ? (
                          <>
                            <Badge variant={f.last.status === 'OK' ? 'success' : 'danger'}>{f.last.status === 'OK' ? 'Worked' : 'Failed'}</Badge>
                            <span className="ml-1.5 text-caption text-ink-muted">{f.last.message}</span>
                          </>
                        ) : <span className="text-ink-subtle">Nothing yet</span>}
                      </TD>
                      <TD muted className="whitespace-nowrap">{when(f.last?.at)}</TD>
                      <TD muted className="whitespace-nowrap">
                        {f.auto_minutes === null ? '—' : f.auto_minutes > 0 ? `every ${f.auto_minutes} min` : 'off'}
                      </TD>
                      <TD align="right">
                        {can.admin && PULLED.has(f.feed) && (
                          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run(f.feed as 'inventory' | 'orders' | 'sales')}>
                            <RefreshCw className={`h-3.5 w-3.5 ${busy === f.feed ? 'animate-spin' : ''}`} aria-hidden="true" />
                            {busy === f.feed ? 'Syncing' : 'Sync now'}
                          </Button>
                        )}
                      </TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            </TableFrame>

            {can.admin && <ConnectionsCard systems={d.systems} />}
          </>
        )}

        {tab === 'orders' && (
          <TableFrame>
            <Table>
              <THead>
                <tr>
                  <TH>Purchase order</TH><TH>Warehouse</TH><TH align="right">Units</TH>
                  <TH align="right">Lines</TH><TH>Status</TH><TH>Delivery</TH><TH>Created</TH><TH />
                </tr>
              </THead>
              <tbody>
                {(po.data ?? []).map((p) => (
                  <TR key={p.id} rail={p.status !== 'SENT' ? 'bad' : p.received_at ? 'none' : 'info'}>
                    <TD mono strong>
                      {p.po_ref}
                      {p.erp_reference && <span className="block text-caption font-normal text-ink-subtle">Ref {p.erp_reference}</span>}
                    </TD>
                    <TD>{p.warehouse_id}</TD>
                    <TD align="right" strong>{n(p.total_units)}</TD>
                    <TD align="right" muted>{p.lines.length}</TD>
                    <TD>
                      <Badge variant={p.status === 'SENT' ? 'success' : 'danger'}>{p.status === 'SENT' ? 'Sent' : 'Not sent'}</Badge>
                      {p.error && <span className="block text-caption text-danger-text">{p.error}</span>}
                    </TD>
                    <TD>
                      {p.status !== 'SENT' ? <span className="text-ink-subtle">—</span>
                        : p.received_at
                          ? <><Badge variant="success">Received</Badge>
                              <span className="block text-caption text-ink-subtle">{when(p.received_at)} · {p.received_by}</span></>
                          : <Badge variant="default">On its way</Badge>}
                    </TD>
                    <TD muted className="whitespace-nowrap">{when(p.created_at)} · {p.created_by}</TD>
                    <TD align="right">
                      {p.status === 'FAILED' && can.edit && (
                        <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(p.id)}>Send again</Button>
                      )}
                      {p.status === 'SENT' && !p.received_at && can.edit && (
                        <Button size="sm" variant="outline" disabled={receive.isPending} onClick={() => receive.mutate(p.id)}>Mark received</Button>
                      )}
                    </TD>
                  </TR>
                ))}
                {po.data?.length === 0 && <Empty colSpan={8}>No purchase orders yet. Raise one from Ordering.</Empty>}
              </tbody>
            </Table>
            {(retry.isError || receive.isError) && (
              <p role="alert" className="border-t border-surface-line px-3 py-2 text-body-sm text-danger-text">
                {errorMessage(retry.error ?? receive.error)}
              </p>
            )}
          </TableFrame>
        )}

        {tab === 'log' && d && (
          <>
            {can.admin && (
              <div className="flex items-center gap-2">
                <Button size="sm" variant={trail ? 'default' : 'outline'} aria-expanded={trail} onClick={() => setTrail((v) => !v)}>
                  {trail ? 'Show exchanges' : 'Show who did what'}
                </Button>
              </div>
            )}
            <TableFrame>
              <Table>
                <THead>
                  <tr>
                    <TH>When</TH>{trail ? <><TH>Person</TH><TH>Action</TH></> : <><TH>Exchange</TH><TH>Result</TH></>}<TH>Detail</TH>
                  </tr>
                </THead>
                <tbody>
                  {trail
                    ? (audit.data ?? []).map((a) => (
                      <TR key={a.id}>
                        <TD muted className="whitespace-nowrap">{when(a.at)}</TD>
                        <TD strong>{a.username}</TD>
                        <TD>{a.action.replace(/_/g, ' ')}</TD>
                        <TD muted>{a.detail}</TD>
                      </TR>
                    ))
                    : d.runs.map((r) => (
                      <TR key={r.id} rail={r.status === 'FAILED' ? 'bad' : 'none'}>
                        <TD muted className="whitespace-nowrap">{when(r.at)}</TD>
                        <TD strong>{r.feed}</TD>
                        <TD><Badge variant={r.status === 'OK' ? 'success' : 'danger'}>{r.status === 'OK' ? 'Worked' : 'Failed'}</Badge></TD>
                        <TD muted>{r.message}</TD>
                      </TR>
                    ))}
                  {((trail ? audit.data?.length : d.runs.length) ?? 0) === 0 && <Empty colSpan={4}>Nothing recorded yet.</Empty>}
                </tbody>
              </Table>
            </TableFrame>
          </>
        )}

        {tab === 'feeds' && d && (pending.data?.count ?? 0) > 0 && (
          <p className="text-caption text-ink-subtle">
            {n(pending.data?.count)} approved orders are holding{' '}
            {n((pending.data?.orders ?? []).reduce((a, o) => a + o.qty, 0))} units until the warehouse confirms they shipped.
          </p>
        )}
      </PageBody>
    </>
  );
}
