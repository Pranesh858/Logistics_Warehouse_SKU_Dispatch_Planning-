'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice } from '@/components/ui/section';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { errorMessage } from '@/lib/api';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useAuth, useCan, useScope } from '@/features/auth/store';
import { useCurrentPlan, usePlan, usePlanHistory, useRecalculate, useRetryExports } from '../hooks';
import type { Plan } from '../types';
import { ApprovePanel } from './ApprovePanel';
import { fmt, fmtDate, PLAN_LABEL, TRIGGER_LABEL } from './format';
import { OutlookTable } from './OutlookTable';
import { PlanTable } from './PlanTable';
import { TruckPlan } from './TruckPlan';
import { TruckSetup } from './TruckSetup';

type Tab = 'orders' | 'trucks' | 'setup' | 'outlook' | 'history';

const TABS: [Tab, string][] = [
  ['orders', 'Orders'], ['trucks', 'Truck loading'], ['setup', 'Trucks'], ['outlook', 'Stock outlook'], ['history', 'History'],
];

const PLAN_TONE = (status: Plan['status']) =>
  status === 'RECOMMENDED' ? 'warning' : status === 'PARTIALLY_EXPORTED' ? 'danger' : status === 'SUPERSEDED' ? 'secondary' : 'success';

/** The plan: what would be dispatched, on which truck, and the one action that sends it. */
export function DispatchPage() {
  const current = useCurrentPlan();
  const history = usePlanHistory();
  const recalc = useRecalculate();
  const can = useCan();
  const wh = useScope();
  const user = useAuth((s) => s.user);
  const [tab, setTab] = useState<Tab>('orders');
  const [viewId, setViewId] = useState<number | undefined>();
  const viewed = usePlan(viewId);

  const plan: Plan | null | undefined = viewId !== undefined ? viewed.data : current.data;
  const isCurrent = viewId === undefined || viewId === current.data?.id;

  if (current.isLoading) {
    return (<><PageHeader title="Dispatch" /><PageBody><p className="py-16 text-center text-body-sm text-ink-muted">Loading the recommended plan…</p></PageBody></>);
  }
  if (current.isError) {
    return (<><PageHeader title="Dispatch" /><PageBody><Notice>{errorMessage(current.error)}</Notice></PageBody></>);
  }
  if (!plan) {
    return (
      <>
        <PageHeader title="Dispatch" actions={<WarehouseSwitch />} />
        <PageBody>
          <div className="rounded-md border border-dashed border-surface-rule bg-surface px-6 py-12 text-center">
            <p className="text-body text-ink-body">No open orders yet.</p>
            <p className="mt-1 text-caption text-ink-muted">A plan is recommended automatically as soon as orders arrive.</p>
            {can.edit && <Button className="mt-4" size="sm" variant="outline" onClick={() => recalc.mutate()} disabled={recalc.isPending}>Check again</Button>}
          </div>
        </PageBody>
      </>
    );
  }

  const s = plan.summary;
  const waiting = plan.status === 'RECOMMENDED';
  const live = waiting && isCurrent && can.edit;
  const sent = plan.lines.filter((l) => l.export_status === 'SENT').length;

  return (
    <>
      <PageHeader
        title={`Plan v${plan.version}${wh ? ` · ${wh}` : ''}`}
        lead={waiting
          ? `Recommended ${fmtDate(plan.created_at)}. Nothing reaches the WMS until you approve.`
          : plan.approved_by
            ? `Approved by ${plan.approved_by} on ${fmtDate(plan.approved_at as string)}.`
            : `Created ${fmtDate(plan.created_at)}.`}
        actions={
          <>
            <Badge variant={PLAN_TONE(plan.status)}>{PLAN_LABEL[plan.status]}</Badge>
            <WarehouseSwitch />
            {!isCurrent && <Button size="sm" variant="outline" onClick={() => setViewId(undefined)}>Back to current</Button>}
            {live && <ApprovePanel plan={plan} />}
          </>
        }
      >
        <div role="tablist" aria-label="Plan sections" className="flex gap-0.5">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} type="button" onClick={() => setTab(k)}
              className={`rounded-md px-2.5 py-1 text-caption font-medium transition-colors ${
                tab === k ? 'bg-primary-soft text-primary' : 'text-ink-muted hover:bg-surface-subtle hover:text-ink-heading'}`}>
              {label}
            </button>
          ))}
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {!can.edit && (
          <Notice tone="info">View only. You can read every plan, but a planner or admin approves it.</Notice>
        )}
        {user?.role === 'planner' && live && (
          <Notice tone="info">
            You plan <strong>{wh}</strong>. Approving sends this warehouse&rsquo;s orders; other warehouses are approved by their own planners.
          </Notice>
        )}
        {plan.status === 'PARTIALLY_EXPORTED' && <RetryBanner plan={plan} />}
        {plan.status === 'EXPORTED' && <Notice tone="good">All {fmt(s.orders_to_send || sent)} approved orders reached the WMS.</Notice>}
        {waiting && s.unassigned_orders > 0 && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-body-sm text-warning-text">
            <span>{fmt(s.unassigned_orders)} {s.unassigned_orders === 1 ? 'order does' : 'orders do'} not fit on any truck and will not be sent.</span>
            <Button size="sm" variant="outline" onClick={() => setTab('trucks')}>See truck loading</Button>
          </div>
        )}

        <MetricBand className="lg:grid-cols-6">
          <Metric label="Orders" value={fmt(s.orders)} note={`${s.overridden + s.rejected} changed by hand`} />
          <Metric label="Demand covered" value={`${s.coverage_pct}%`} note={`${fmt(s.units_allocated)} of ${fmt(s.units_ordered)} units`} />
          <Metric label={waiting ? 'Will be sent' : 'Sent'} value={fmt(waiting ? s.orders_to_send : sent)} note={`${fmt(s.units_to_send)} units`} />
          <Metric label="Trucks" value={fmt(s.trucks_used)} note={waiting ? `of ${fmt(plan.trucks.length)} available` : undefined} />
          <Metric label="Without a truck" value={fmt(s.unassigned_orders)} note="not sent until loaded" tone={s.unassigned_orders ? 'warn' : 'neutral'} />
          <Metric label="Need attention" value={fmt(s.exceptions)} note={`${fmt(s.at_risk)} may miss their date`} tone={s.at_risk ? 'bad' : s.exceptions ? 'warn' : 'neutral'} />
        </MetricBand>

        <div className="grid gap-px overflow-hidden rounded-md border border-surface-line bg-surface-line sm:grid-cols-3">
          {(['Premium', 'Standard', 'Basic'] as const).map((t) => {
            const pct = s.by_tier[t]?.coverage_pct ?? 0;
            return (
              <div key={t} className="bg-surface px-4 py-2.5">
                <div className="flex items-baseline justify-between text-body-sm">
                  <span className="font-medium text-ink-heading">{t}</span>
                  <span className="tabular text-caption text-ink-muted">{pct}% covered</span>
                </div>
                <div className="mt-1.5 h-1 overflow-hidden rounded-pill bg-surface-subtle" role="img" aria-label={`${t} orders ${pct}% covered`}>
                  <div className={`h-full ${pct >= 90 ? 'bg-success' : pct >= 60 ? 'bg-primary' : 'bg-warning'}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>

        {tab === 'orders' && <PlanTable key={plan.id} plan={plan} editable={live} />}
        {tab === 'trucks' && <TruckPlan key={plan.id} plan={plan} editable={live} />}
        {tab === 'setup' && <TruckSetup readOnly={!can.edit} warehouses={Array.from(new Set(plan.lines.map((l) => l.warehouse_id)))} />}
        {tab === 'outlook' && <OutlookTable planId={plan.id} />}
        {tab === 'history' && (
          <ul className="divide-y divide-surface-line overflow-hidden rounded-md border border-surface-line bg-surface">
            {(history.data ?? []).map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-body-sm">
                <span className="font-medium text-ink-heading">v{p.version}</span>
                <Badge variant={PLAN_TONE(p.status)}>{PLAN_LABEL[p.status]}</Badge>
                <span className="text-caption text-ink-muted">{fmtDate(p.created_at)} · {TRIGGER_LABEL[p.trigger] ?? p.trigger}</span>
                {p.approved_by && <span className="text-caption text-ink-muted">by {p.approved_by}</span>}
                <Button className="ml-auto" size="sm" variant="outline"
                  onClick={() => { setViewId(p.id === current.data?.id ? undefined : p.id); setTab('orders'); }}>
                  Open
                </Button>
              </li>
            ))}
          </ul>
        )}
      </PageBody>
    </>
  );
}

function RetryBanner({ plan }: { plan: Plan }) {
  const retry = useRetryExports(plan.id);
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">
      <span>
        {plan.summary.failed_exports} approved order(s) could not reach the WMS. Their stock stays held.
        {retry.isError && ` ${errorMessage(retry.error)}`}
      </span>
      <Button size="sm" variant="destructive" onClick={() => retry.mutate()} disabled={retry.isPending}>
        {retry.isPending ? 'Retrying…' : 'Retry sending'}
      </Button>
    </div>
  );
}
