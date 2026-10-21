'use client';

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useCan } from '@/features/auth/store';
import { errorMessage } from '@/lib/api';
import { useIntegrationStatus, usePurchaseOrders, useRetryPurchase, useSync } from '../hooks';
import type { Feed } from '../types';

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Never';

const FEED_HELP: Record<Feed['feed'], string> = {
  inventory: 'Live stock per SKU and warehouse. Every plan and order list uses it.',
  orders: 'New customer orders. Each new order rebuilds the dispatch plan.',
  sales: 'Daily sales added to the history the forecast learns from.',
  purchasing: 'Purchase orders raised from Units to order.',
};

export function IntegrationsPage() {
  const can = useCan();
  const status = useIntegrationStatus();
  const sync = useSync();
  const po = usePurchaseOrders();
  const retry = useRetryPurchase();
  const [log, setLog] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const run = (feed: 'inventory' | 'orders' | 'sales') => {
    setBusy(feed);
    sync.mutate(feed, { onSettled: () => setBusy(null) });
  };
  const simulated = status.data?.feeds.some((f) => f.mode === 'simulator') || status.data?.dispatch_export.mode === 'simulator';

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header className="max-w-3xl">
        <h1 className="text-[1.5rem] font-semibold tracking-tight text-ink-heading">Integrations</h1>
        <p className="mt-1 text-body text-ink-muted">
          How the planner exchanges data with the warehouse system (WMS) and the ERP: what comes in, what goes out, and whether the last exchange worked.
        </p>
      </header>

      {simulated && (
        <p className="rounded-lg border border-warning-border bg-warning-soft px-4 py-3 text-body-sm text-warning-text">
          Some connections run on built-in simulators, so no real WMS or ERP is contacted. To connect the real systems, set <code>WMS_BASE_URL</code> and{' '}
          <code>ERP_BASE_URL</code> on the backend.
        </p>
      )}
      {status.isError && <p role="alert" className="text-danger-text">{errorMessage(status.error)}</p>}
      {status.isLoading && <p className="py-10 text-center text-ink-muted">Loading…</p>}

      {status.data && (
        <>
          <section aria-label="Connections" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {status.data.feeds.map((f) => (
              <Card key={f.feed}>
                <CardContent className="space-y-2 pt-6">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-body font-semibold text-ink-heading">{f.label}</p>
                      <p className="text-caption text-ink-muted">{f.feed === 'inventory' ? 'From' : f.feed === 'purchasing' ? 'To' : 'From'} the {f.system}</p>
                    </div>
                    <Badge variant={f.mode === 'live' ? 'success' : 'secondary'}>{f.mode === 'live' ? 'Live' : 'Simulator'}</Badge>
                  </div>
                  <p className="text-caption text-ink-muted">{FEED_HELP[f.feed]}</p>
                  <div className="text-body-sm">
                    {f.last ? (
                      <>
                        <Badge variant={f.last.status === 'OK' ? 'success' : 'danger'}>{f.last.status === 'OK' ? 'Last exchange worked' : 'Last exchange failed'}</Badge>
                        <p className="mt-1 text-ink-body">{f.last.message}</p>
                        <p className="text-caption text-ink-subtle">{when(f.last.at)}</p>
                      </>
                    ) : (
                      <p className="text-ink-muted">Nothing exchanged yet.</p>
                    )}
                  </div>
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-caption text-ink-subtle">
                      {f.auto_minutes === null ? '' : f.auto_minutes > 0 ? `Automatic every ${f.auto_minutes} min` : 'Manual or pushed by the system'}
                    </span>
                    {can.admin && f.feed !== 'purchasing' && (
                      <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => run(f.feed as 'inventory' | 'orders' | 'sales')}>
                        <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${busy === f.feed ? 'animate-spin' : ''}`} aria-hidden="true" />
                        {busy === f.feed ? 'Syncing…' : 'Sync now'}
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </section>

          <p className="text-body-sm text-ink-muted">
            Approved dispatch orders go to the {status.data.dispatch_export.system} ({status.data.dispatch_export.mode === 'live' ? 'live' : 'simulator'}).{' '}
            {status.data.live_stock_skus > 0 ? `${status.data.live_stock_skus} SKU-warehouse stock levels currently come from the WMS.` : 'Stock still comes from the sales history until the first stock sync.'}{' '}
            {status.data.webhooks_enabled ? 'The WMS and ERP can also push changes to the webhooks.' : 'Webhooks are off.'}
          </p>
          {sync.isError && <p role="alert" className="text-body-sm text-danger-text">{errorMessage(sync.error)}</p>}
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Purchase orders</CardTitle>
          <CardDescription>Raised from Units to order and sent to the ERP, one per warehouse.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-body-sm">
            <thead>
              <tr className="border-b border-surface-line text-left text-label text-ink-muted">
                <th className="py-2 pr-4">Purchase order</th><th className="pr-4">Warehouse</th><th className="pr-4 text-right">Units</th>
                <th className="pr-4 text-right">Lines</th><th className="pr-4">Status</th><th className="pr-4">Created</th><th />
              </tr>
            </thead>
            <tbody>
              {(po.data ?? []).map((p) => (
                <tr key={p.id} className="border-b border-surface-line align-top">
                  <td className="py-2 pr-4"><span className="font-medium text-ink-heading">{p.po_ref}</span>
                    {p.erp_reference && <span className="block text-caption text-ink-subtle">Ref {p.erp_reference}</span>}</td>
                  <td className="pr-4">{p.warehouse_id}</td>
                  <td className="pr-4 text-right tabular-nums">{p.total_units.toLocaleString()}</td>
                  <td className="pr-4 text-right tabular-nums">{p.lines.length}</td>
                  <td className="pr-4">
                    <Badge variant={p.status === 'SENT' ? 'success' : 'danger'}>{p.status === 'SENT' ? 'Sent to ERP' : 'Not sent'}</Badge>
                    {p.error && <span className="block text-caption text-danger-text">{p.error}</span>}
                  </td>
                  <td className="pr-4 text-ink-muted">{when(p.created_at)} by {p.created_by}</td>
                  <td className="text-right">
                    {p.status === 'FAILED' && can.edit && (
                      <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(p.id)}>Send again</Button>
                    )}
                  </td>
                </tr>
              ))}
              {po.data?.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-ink-muted">No purchase orders yet. Create one from Demand forecast, Units to order.</td></tr>
              )}
            </tbody>
          </table>
          {retry.isError && <p role="alert" className="mt-2 text-danger-text">{errorMessage(retry.error)}</p>}
        </CardContent>
      </Card>

      {status.data && (
        <section aria-label="Activity">
          <Button variant="outline" size="sm" aria-expanded={log} onClick={() => setLog((v) => !v)}>{log ? 'Hide activity log' : 'Show activity log'}</Button>
          {log && (
            <Card className="mt-3">
              <CardContent className="pt-6">
                <ul className="space-y-1.5 text-body-sm">
                  {status.data.runs.map((r) => (
                    <li key={r.id} className="flex flex-wrap gap-x-3">
                      <span className="w-32 shrink-0 text-ink-subtle">{when(r.at)}</span>
                      <Badge variant={r.status === 'OK' ? 'success' : 'danger'}>{r.status}</Badge>
                      <span className="text-ink-heading">{r.feed}</span>
                      <span className="text-ink-muted">{r.message}</span>
                    </li>
                  ))}
                  {status.data.runs.length === 0 && <li className="text-ink-muted">No activity yet.</li>}
                </ul>
              </CardContent>
            </Card>
          )}
        </section>
      )}
    </div>
  );
}
