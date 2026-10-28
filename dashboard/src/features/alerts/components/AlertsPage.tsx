'use client';

import { useState } from 'react';
import { AlertTriangle, Check, Info, OctagonAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice } from '@/components/ui/section';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { errorMessage } from '@/lib/api';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useAuth, useCan } from '@/features/auth/store';
import { useAcknowledge, useAlerts, useAlertSummary, useResolve, useSweep, useTestDelivery } from '../hooks';
import type { Alert, Severity } from '../types';

const LOOK: Record<Severity, { icon: React.ReactNode; bar: string; label: string }> = {
  CRITICAL: { icon: <OctagonAlert className="h-4 w-4" />, bar: 'bg-danger', label: 'Critical' },
  WARNING: { icon: <AlertTriangle className="h-4 w-4" />, bar: 'bg-warning', label: 'Warning' },
  INFO: { icon: <Info className="h-4 w-4" />, bar: 'bg-primary', label: 'For information' },
};

const KIND_LABEL: Record<string, string> = {
  stockout: 'Out of stock',
  low_cover: 'Running out',
  sync_failed: 'Feed failing',
  export_failed: 'Not sent to WMS',
  transfer_overdue: 'Transfer late',
  retrain_rejected: 'Retrain refused',
  retrain_done: 'New model',
};

const ago = (iso: string | null) => {
  if (!iso) return '';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} days ago`;
};

/**
 * What needs a person.
 *
 * The list holds one row per problem and empties itself when a condition clears, so what is on screen is
 * what is wrong now. Acknowledging says somebody is on it; the alert stays until the condition goes away.
 */
export function AlertsPage() {
  const [showResolved, setShowResolved] = useState(false);
  const summary = useAlertSummary();
  const list = useAlerts(showResolved ? 'RESOLVED' : undefined);
  const sweep = useSweep();
  const can = useCan();
  const isAdmin = useAuth((s) => s.user?.role === 'admin');

  const s = summary.data;

  return (
    <>
      <PageHeader
        title="Alerts"
        lead={s && s.total === 0
          ? 'Nothing needs attention.'
          : 'One row per problem. A row disappears when the condition behind it clears.'}
        actions={
          <>
            <WarehouseSwitch />
            <Button size="sm" variant="outline" onClick={() => setShowResolved((v) => !v)}>
              {showResolved ? 'Back to live' : 'Recently closed'}
            </Button>
            {can.edit && (
              <Button size="sm" variant="outline" onClick={() => sweep.mutate()} disabled={sweep.isPending}>
                {sweep.isPending ? 'Checking…' : 'Check now'}
              </Button>
            )}
          </>
        }
      />
      <PageBody className="space-y-4">
        {s && !s.enabled && <Notice tone="warn">Alerts are switched off in the configuration (ALERTS_ENABLED).</Notice>}
        {s && <DeliveryLine channels={s.channels} isAdmin={isAdmin} />}

        {s && (
          <MetricBand className="lg:grid-cols-4">
            <Metric label="Critical" value={String(s.critical)} note="costing money now"
              tone={s.critical ? 'bad' : 'neutral'} />
            <Metric label="Warnings" value={String(s.warning)} note="will cost money soon"
              tone={s.warning ? 'warn' : 'neutral'} />
            <Metric label="Being handled" value={String(s.acknowledged)} note="somebody is on it" />
            <Metric label="Needs someone" value={String(s.open)} note="nobody has picked it up"
              tone={s.open ? 'warn' : 'good'} />
          </MetricBand>
        )}

        {list.isError && <Notice>{errorMessage(list.error)}</Notice>}
        {list.isLoading && <p className="py-10 text-center text-body-sm text-ink-muted">Loading…</p>}

        {list.data?.length === 0 && (
          <div className="rounded-md border border-dashed border-surface-rule bg-surface px-6 py-12 text-center">
            <p className="text-body text-ink-body">
              {showResolved ? 'Nothing has been closed recently.' : 'Nothing needs attention.'}
            </p>
            {!showResolved && (
              <p className="mt-1 text-caption text-ink-muted">
                Stock levels, the feeds from your other systems and overdue transfers are all being watched.
              </p>
            )}
          </div>
        )}

        <ul className="space-y-2">
          {(list.data ?? []).map((a) => (
            <AlertRow key={a.id} alert={a} editable={can.edit && !showResolved} />
          ))}
        </ul>
      </PageBody>
    </>
  );
}

function DeliveryLine({ channels, isAdmin }: { channels: string[]; isAdmin: boolean }) {
  const test = useTestDelivery();
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-surface-line bg-surface-muted px-3 py-2 text-caption text-ink-muted">
      <span>
        {channels.length === 0
          ? 'Alerts appear here only. To have them pushed out, set a webhook or an email address in the configuration.'
          : `Also pushed to: ${channels.join(' and ')}.`}
        {test.data && ` ${test.data.message}`}
        {test.isError && ` ${errorMessage(test.error)}`}
      </span>
      {isAdmin && channels.length > 0 && (
        <Button size="sm" variant="ghost" onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? 'Sending…' : 'Send a test'}
        </Button>
      )}
    </div>
  );
}

function AlertRow({ alert, editable }: { alert: Alert; editable: boolean }) {
  const ack = useAcknowledge();
  const resolve = useResolve();
  const [closing, setClosing] = useState(false);
  const [note, setNote] = useState('');
  const look = LOOK[alert.severity];
  const busy = ack.isPending || resolve.isPending;

  return (
    <li className="flex overflow-hidden rounded-md border border-surface-line bg-surface">
      <span className={`w-1 shrink-0 ${look.bar}`} aria-hidden="true" />
      <div className="min-w-0 flex-1 px-4 py-3">
        <div className="flex flex-wrap items-start gap-2">
          <span className={alert.severity === 'CRITICAL' ? 'mt-0.5 text-danger' : alert.severity === 'WARNING' ? 'mt-0.5 text-warning' : 'mt-0.5 text-primary'}>
            {look.icon}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-body font-medium text-ink-heading">{alert.title}</p>
            {alert.detail && <p className="mt-0.5 text-body-sm text-ink-body">{alert.detail}</p>}
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-ink-muted">
              <Badge variant="secondary">{KIND_LABEL[alert.kind] ?? alert.kind}</Badge>
              {alert.warehouse_id && <span>{alert.warehouse_id}</span>}
              <span>{ago(alert.last_seen)}</span>
              {alert.occurrences > 1 && <span>seen {alert.occurrences} times</span>}
              {alert.acknowledged_by && <span>· {alert.acknowledged_by} is on it</span>}
              {alert.resolved_note && <span>· {alert.resolved_note}</span>}
            </p>
          </div>
          {editable && (
            <div className="flex shrink-0 items-center gap-1.5">
              {alert.status === 'OPEN' && (
                <Button size="sm" variant="outline" onClick={() => ack.mutate(alert.id)} disabled={busy}>
                  <Check className="mr-1 h-3 w-3" aria-hidden="true" />
                  I&rsquo;m on it
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setClosing((v) => !v)} disabled={busy}>
                Close
              </Button>
            </div>
          )}
        </div>

        {closing && (
          <form
            className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-surface-line pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              resolve.mutate({ id: alert.id, note }, { onSuccess: () => { setClosing(false); setNote(''); } });
            }}
          >
            <input
              autoFocus
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What happened?"
              aria-label="Why this alert is being closed"
              className="min-w-0 flex-1 rounded-sm border border-surface-rule bg-surface px-2 py-1 text-caption text-ink-body placeholder:text-ink-muted focus:border-primary focus:outline-none"
            />
            <Button size="sm" type="submit" disabled={busy}>Close it</Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setClosing(false)}>Keep</Button>
            <p className="w-full text-caption text-ink-muted">
              If the problem is still real, the next check raises it again.
            </p>
          </form>
        )}
        {(ack.isError || resolve.isError) && (
          <p className="mt-2 text-caption text-danger-text">{errorMessage(ack.error ?? resolve.error)}</p>
        )}
      </div>
    </li>
  );
}
