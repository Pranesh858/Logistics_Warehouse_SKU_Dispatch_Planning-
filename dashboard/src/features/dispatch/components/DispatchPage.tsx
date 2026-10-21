'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { errorMessage } from '@/lib/api';
import { useCurrentPlan, usePlan, usePlanHistory, useRecalculate, useRetryExports } from '../hooks';
import type { Plan } from '../types';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useAuth, useCan, useScope } from '@/features/auth/store';
import { ApprovePanel } from './ApprovePanel';
import { fmt, fmtDate, PLAN_LABEL, TRIGGER_LABEL } from './format';
import { OutlookTable } from './OutlookTable';
import { PlanTable } from './PlanTable';
import { TruckPlan } from './TruckPlan';
import { TruckSetup } from './TruckSetup';

type Tab = 'orders' | 'trucks' | 'setup' | 'outlook' | 'history';

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

  if (current.isLoading) return <Shell><p className="py-16 text-center text-ink-muted">Loading the recommended plan…</p></Shell>;
  if (current.isError) {
    return <Shell><Card><CardContent role="alert" className="py-10 text-center text-danger-text">{errorMessage(current.error)}</CardContent></Card></Shell>;
  }
  if (!plan) {
    return (
      <Shell>
        <Card><CardContent className="py-12 text-center">
          <p className="text-body text-ink-muted mb-4">There are no open orders yet. A plan is recommended automatically as soon as orders arrive.</p>
          {can.edit && <Button variant="outline" onClick={() => recalc.mutate()} disabled={recalc.isPending}>Check again</Button>}
        </CardContent></Card>
      </Shell>
    );
  }

  const s = plan.summary;
  const waiting = plan.status === 'RECOMMENDED';

  return (
    <Shell>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[1.5rem] font-semibold tracking-tight text-ink-heading">Dispatch plan v{plan.version}{wh ? `: ${wh}` : ''}</h1>
            <Badge variant={waiting ? 'warning' : plan.status === 'PARTIALLY_EXPORTED' ? 'danger' : plan.status === 'SUPERSEDED' ? 'secondary' : 'success'}>
              {PLAN_LABEL[plan.status]}
            </Badge>
          </div>
          <p className="text-body-sm text-ink-muted mt-1">
            {waiting
              ? <>Recommended by the system ({TRIGGER_LABEL[plan.trigger] ?? plan.trigger}, {fmtDate(plan.created_at)}). Nothing reaches the WMS until you approve.</>
              : plan.approved_by
                ? <>Approved by {plan.approved_by} on {fmtDate(plan.approved_at as string)}.</>
                : <>Created {fmtDate(plan.created_at)}.</>}
          </p>
          {!isCurrent && (
            <Button variant="link" className="mt-1" onClick={() => setViewId(undefined)}>Back to the current plan</Button>
          )}
        </div>
        <div className="flex flex-col items-end gap-3">
          <WarehouseSwitch />
          {waiting && isCurrent && can.edit && <ApprovePanel plan={plan} />}
        </div>
      </header>

      {!can.edit && (
        <p role="status" className="rounded-md border border-surface-line bg-surface-subtle px-4 py-3 text-body-sm text-ink-body">
          You have view-only access. You can read every plan, but only a planner or admin can change or approve it.
        </p>
      )}
      {user?.role === 'planner' && waiting && isCurrent && (
        <p role="status" className="rounded-md border border-surface-line bg-surface-subtle px-4 py-3 text-body-sm text-ink-body">
          You are planning <strong>{wh}</strong> only. Approving sends this warehouse&rsquo;s orders to the WMS; other warehouses are approved by their own planners.
        </p>
      )}

      {plan.status === 'PARTIALLY_EXPORTED' && <RetryBanner plan={plan} />}
      {plan.status === 'EXPORTED' && (
        <p role="status" className="rounded-md border border-success-border bg-success-soft px-4 py-3 text-body-sm text-success-text">
          All {fmt(s.orders_to_send || plan.lines.filter((l) => l.export_status === 'SENT').length)} approved orders were sent to the WMS.
        </p>
      )}

      {waiting && s.unassigned_orders > 0 && (
        <p role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning-border bg-warning-soft px-4 py-3 text-body-sm text-warning-text">
          <span>{fmt(s.unassigned_orders)} {s.unassigned_orders === 1 ? 'order does' : 'orders do'} not fit on any truck and will not be sent.</span>
          <Button size="sm" variant="outline" onClick={() => setTab('trucks')}>See truck loading</Button>
        </p>
      )}

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-6">
        <Kpi label="Orders" value={fmt(s.orders)} sub={`${s.overridden + s.rejected} changed by planner`} />
        <Kpi label="Demand covered" value={`${s.coverage_pct}%`} sub={`${fmt(s.units_allocated)} of ${fmt(s.units_ordered)} units`} />
        <Kpi label={waiting ? 'Will be sent' : 'Orders sent'} value={waiting ? fmt(s.orders_to_send) : fmt(plan.lines.filter((l) => l.export_status === 'SENT').length)} sub={`${fmt(s.units_to_send)} units`} />
        <Kpi label="Trucks used" value={fmt(s.trucks_used)} sub={waiting ? `of ${fmt(plan.trucks.length)} available` : undefined} />
        <Kpi label="Without a truck" value={fmt(s.unassigned_orders)} sub="not sent until loaded" tone={s.unassigned_orders ? 'warn' : undefined} />
        <Kpi label="Need attention" value={fmt(s.exceptions)} sub={`${fmt(s.at_risk)} at risk of missing due date`} tone={s.at_risk ? 'danger' : s.exceptions ? 'warn' : undefined} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {(['Premium', 'Standard', 'Basic'] as const).map((t) => (
          <div key={t} className="rounded-lg border border-surface-line bg-surface px-4 py-3">
            <div className="flex justify-between text-body-sm"><span className="text-ink-body font-medium">{t}</span>
              <span className="tabular-nums text-ink-muted">{s.by_tier[t]?.coverage_pct ?? 0}% covered</span></div>
            <div className="mt-2 h-2 rounded-pill bg-surface-subtle overflow-hidden" role="img" aria-label={`${t} orders ${s.by_tier[t]?.coverage_pct ?? 0}% covered`}>
              <div className="h-full bg-primary" style={{ width: `${s.by_tier[t]?.coverage_pct ?? 0}%` }} />
            </div>
          </div>
        ))}
      </div>

      <Card>
        <div role="tablist" aria-label="Plan sections" className="flex gap-1 border-b border-surface-line px-4 pt-2">
          {([['orders', 'Orders'], ['trucks', 'Truck loading'], ['setup', 'Truck setup'], ['outlook', 'Stock outlook'], ['history', 'Plan history']] as [Tab, string][]).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} type="button" onClick={() => setTab(k)}
              className={`px-3 py-2 text-body-sm font-semibold border-b-2 -mb-px ${tab === k ? 'border-primary text-primary' : 'border-transparent text-ink-muted hover:text-ink-heading'}`}>
              {label}
            </button>
          ))}
        </div>
        <CardContent className="pt-5">
          {tab === 'orders' && <PlanTable key={plan.id} plan={plan} editable={waiting && isCurrent && can.edit} />}
          {tab === 'trucks' && <TruckPlan key={plan.id} plan={plan} editable={waiting && isCurrent && can.edit} />}
          {tab === 'setup' && <TruckSetup readOnly={!can.edit} warehouses={Array.from(new Set(plan.lines.map((l) => l.warehouse_id)))} />}
          {tab === 'outlook' && <OutlookTable planId={plan.id} />}
          {tab === 'history' && (
            <ul className="divide-y divide-surface-line">
              {(history.data ?? []).map((p) => (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-body-sm">
                  <span><strong>v{p.version}</strong> <span className="text-ink-muted">{fmtDate(p.created_at)}, {TRIGGER_LABEL[p.trigger] ?? p.trigger}</span></span>
                  <span className="flex items-center gap-3">
                    <Badge variant={p.status === 'RECOMMENDED' ? 'warning' : p.status === 'SUPERSEDED' ? 'secondary' : p.status === 'PARTIALLY_EXPORTED' ? 'danger' : 'success'}>{PLAN_LABEL[p.status]}</Badge>
                    {p.approved_by && <span className="text-ink-muted">by {p.approved_by}</span>}
                    <Button size="sm" variant="outline" onClick={() => { setViewId(p.id === current.data?.id ? undefined : p.id); setTab('orders'); }}>View</Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">{children}</div>;
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'warn' | 'danger' }) {
  return (
    <div className="rounded-xl border border-surface-line bg-surface px-4 py-3 shadow-card">
      <p className="text-label text-ink-muted">{label}</p>
      <p className={`text-h2 tabular-nums ${tone === 'danger' ? 'text-danger-text' : tone === 'warn' ? 'text-warning-text' : 'text-ink-heading'}`}>{value}</p>
      {sub && <p className="text-caption text-ink-subtle">{sub}</p>}
    </div>
  );
}

function RetryBanner({ plan }: { plan: Plan }) {
  const retry = useRetryExports(plan.id);
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger-border bg-danger-soft px-4 py-3 text-body-sm text-danger-text">
      <span>{plan.summary.failed_exports} approved order(s) could not be sent to the WMS. Their stock stays reserved. {retry.isError && errorMessage(retry.error)}</span>
      <Button size="sm" variant="destructive" onClick={() => retry.mutate()} disabled={retry.isPending}>{retry.isPending ? 'Retrying…' : 'Retry sending'}</Button>
    </div>
  );
}
