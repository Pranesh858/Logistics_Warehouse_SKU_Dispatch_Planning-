'use client';

import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Metric, MetricBand } from '@/components/ui/metric';
import { Notice, Section } from '@/components/ui/section';
import { Empty, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useAuth, useScope } from '@/features/auth/store';
import { useCurrentPlan, useOutlook } from '@/features/dispatch/hooks';
import { useOrders } from '@/features/forecast/hooks';
import { useIntegrationStatus } from '@/features/integrations/hooks';
import { errorMessage } from '@/lib/api';

const n = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d });

type Job = { what: string; detail: string; href: string; cta: string; tone: 'bad' | 'warn' | 'info' };

/** The first screen is a queue, not a welcome: what is waiting for this person, most pressing first. */
export function TodayPage() {
  const user = useAuth((s) => s.user);
  const scope = useScope();
  const plan = useCurrentPlan();
  const orders = useOrders(7, true, scope ?? undefined);
  const systems = useIntegrationStatus();
  const outlook = useOutlook(plan.data?.id, !!plan.data);

  const s = plan.data?.summary;
  const draft = plan.data?.status === 'RECOMMENDED' ? plan.data : null;
  const need = orders.data?.summary;
  const waitingConfirm = systems.data?.awaiting_confirmation ?? 0;
  const brokenFeeds = (systems.data?.feeds ?? []).filter((f) => f.last?.status === 'FAILED');

  const jobs: Job[] = [];
  if (draft && s && s.orders_to_send > 0) {
    jobs.push({
      what: `Plan v${draft.version} is ready to approve`,
      detail: `${n(s.orders_to_send)} orders, ${n(s.units_to_send)} units, on ${n(s.trucks_used)} ${s.trucks_used === 1 ? 'truck' : 'trucks'}`,
      href: '/dispatch', cta: 'Review and approve', tone: 'info',
    });
  }
  if (s && s.exceptions > 0) {
    jobs.push({
      what: `${n(s.exceptions)} orders cannot be filled`,
      detail: 'Short of stock, held or blocked. They stay open until stock arrives.',
      href: '/dispatch', cta: 'See exceptions', tone: 'warn',
    });
  }
  if (need && need.order_now > 0) {
    jobs.push({
      what: `${n(need.order_now)} SKUs are about to run out`,
      detail: `Under three days of cover. ${n(need.units_to_order)} units to order across ${n(need.skus_to_order)} lines.`,
      href: '/ordering', cta: 'Open ordering', tone: 'bad',
    });
  }
  if (waitingConfirm > 0) {
    jobs.push({
      what: `${n(waitingConfirm)} approved orders are unconfirmed`,
      detail: 'Their stock stays held until the warehouse says the goods have left.',
      href: '/integrations', cta: 'Confirm dispatches', tone: 'warn',
    });
  }
  brokenFeeds.forEach((f) =>
    jobs.push({
      what: `${f.label} did not come through`,
      detail: f.last?.message ?? '', href: '/integrations', cta: 'Check connection', tone: 'bad',
    }),
  );

  const shorts = (outlook.data ?? [])
    .filter((r) => r.outlook === 'STOCKED_OUT' || r.outlook === 'WILL_STOCK_OUT')
    .sort((a, b) => (a.days_of_cover ?? 0) - (b.days_of_cover ?? 0))
    .slice(0, 6);
  const buy = (orders.data?.rows ?? []).slice(0, 6);

  return (
    <>
      <PageHeader
        title="Today"
        lead={`${new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })} · ${scope ?? 'All warehouses'} · ${user?.name ?? ''}`}
        actions={<WarehouseSwitch />}
      />
      <PageBody className="space-y-5">
        <MetricBand>
          <Metric label="Waiting for approval" value={n(s?.orders_to_send)} note={draft ? `plan v${draft.version}` : 'nothing drafted'}
            tone={s && s.orders_to_send > 0 ? 'neutral' : 'neutral'} />
          <Metric label="Cannot be filled" value={n(s?.exceptions)} note="short of stock or held"
            tone={s && s.exceptions > 0 ? 'warn' : 'neutral'} />
          <Metric label="Units to order, 7 days" value={orders.isLoading ? '…' : n(need?.units_to_order)}
            note={need ? `${n(need.order_now)} urgent` : 'working it out'} tone={need && need.order_now > 0 ? 'bad' : 'neutral'} />
          <Metric label="Awaiting confirmation" value={n(waitingConfirm)} note="stock still held"
            tone={waitingConfirm > 0 ? 'warn' : 'neutral'} />
        </MetricBand>

        {plan.isError && <Notice>{errorMessage(plan.error)}</Notice>}

        <Section title="What needs you" lead={jobs.length ? undefined : 'Nothing is waiting. The plan is approved and stock covers the week.'}>
          {jobs.length > 0 && (
            <ul className="divide-y divide-surface-line overflow-hidden rounded-md border border-surface-line bg-surface">
              {jobs.map((j) => (
                <li key={j.what} style={{ '--rail': j.tone === 'bad' ? '#C13A2E' : j.tone === 'warn' ? '#B4690E' : '#1F4B8E' } as React.CSSProperties}
                  className="state-rail flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-body font-medium text-ink-heading">{j.what}</p>
                    <p className="text-caption text-ink-muted">{j.detail}</p>
                  </div>
                  <Link href={j.href}
                    className="inline-flex items-center gap-1 rounded-md border border-surface-rule px-2.5 py-1.5 text-caption font-medium text-ink-body transition-colors hover:border-ink-subtle hover:text-ink-heading">
                    {j.cta}
                    <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <div className="grid gap-5 xl:grid-cols-2">
          <Section title="Running short" lead="Stock that will not last the forecast period.">
            <TableFrame>
              <Table>
                <THead>
                  <tr>
                    <TH>SKU</TH><TH>Warehouse</TH><TH align="right">On hand</TH>
                    <TH align="right">Demand</TH><TH align="right">Cover</TH>
                  </tr>
                </THead>
                <tbody>
                  {shorts.map((r) => (
                    <TR key={`${r.product_id}-${r.warehouse_id}`} rail={r.outlook === 'STOCKED_OUT' ? 'bad' : 'warn'}>
                      <TD mono strong>#{r.product_id}</TD>
                      <TD>{r.warehouse_id}</TD>
                      <TD align="right">{n(r.stock_after_plan)}</TD>
                      <TD align="right" muted>{n(r.forecast_demand)}</TD>
                      <TD align="right">
                        {r.outlook === 'STOCKED_OUT'
                          ? <Badge variant="danger">Out</Badge>
                          : <span className="text-warning-text">{n(r.days_of_cover, 1)} d</span>}
                      </TD>
                    </TR>
                  ))}
                  {shorts.length === 0 && <Empty colSpan={5}>{outlook.isLoading ? 'Checking stock…' : 'Every SKU covers the period.'}</Empty>}
                </tbody>
              </Table>
            </TableFrame>
          </Section>

          <Section title="Order first" lead="The most urgent lines from the ordering list."
            actions={<Link href="/ordering" className="text-caption font-medium text-primary hover:underline">All lines</Link>}>
            <TableFrame>
              <Table>
                <THead>
                  <tr>
                    <TH>Product</TH><TH>Warehouse</TH><TH align="right">Order</TH><TH align="right">Cover</TH>
                  </tr>
                </THead>
                <tbody>
                  {buy.map((r) => (
                    <TR key={`${r.product_id}-${r.warehouse_id}`} rail={r.priority === 'Order now' ? 'bad' : r.priority === 'Order soon' ? 'warn' : 'none'}>
                      <TD strong className="max-w-[16rem] truncate">{r.product_name}</TD>
                      <TD>{r.warehouse_id}</TD>
                      <TD align="right" strong>{n(r.units_to_order)}</TD>
                      <TD align="right" muted>{r.days_of_cover === null ? '—' : `${n(r.days_of_cover, 1)} d`}</TD>
                    </TR>
                  ))}
                  {buy.length === 0 && <Empty colSpan={4}>{orders.isLoading ? 'Working out what to order…' : 'Stock covers the next seven days.'}</Empty>}
                </tbody>
              </Table>
            </TableFrame>
          </Section>
        </div>
      </PageBody>
    </>
  );
}
