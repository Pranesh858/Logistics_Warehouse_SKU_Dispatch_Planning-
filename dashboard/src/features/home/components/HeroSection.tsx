'use client';

import Link from 'next/link';
import { ArrowRight, BarChart3, LineChart, PackageCheck } from 'lucide-react';
import { useCurrentPlan } from '@/features/dispatch/hooks';

type Waiting = NonNullable<ReturnType<typeof useCurrentPlan>['data']> | null;

/** One line about the plan: what is waiting to be sent, or why nothing is. */
function planNote(plan: Waiting): string | undefined {
  if (!plan) return undefined;
  const s = plan.summary;
  if (s.orders_to_send > 0) {
    return `Plan v${plan.version} is waiting for approval: ${s.orders_to_send} ${s.orders_to_send === 1 ? 'order' : 'orders'} on ${s.trucks_used ?? 0} ${s.trucks_used === 1 ? 'truck' : 'trucks'}`;
  }
  if (s.exceptions > 0) {
    return `Nothing to send right now. ${s.exceptions} ${s.exceptions === 1 ? 'order is' : 'orders are'} waiting for stock.`;
  }
  return 'Nothing to send right now.';
}

export function HeroSection() {
  const plan = useCurrentPlan();
  const waiting = plan.data?.status === 'RECOMMENDED' ? plan.data : null;

  return (
    <div className="mx-auto max-w-5xl px-6 py-14">
      <header className="max-w-2xl">
        <h1 className="text-[2rem] font-semibold leading-tight tracking-tight text-ink-heading">
          Plan tomorrow&rsquo;s dispatch from today&rsquo;s demand
        </h1>
        <p className="mt-3 text-body text-ink-muted">
          The system forecasts demand for every SKU and warehouse, recommends which orders to dispatch and on which trucks,
          and sends the plan to the WMS only after a planner approves it.
        </p>
      </header>

      <section aria-label="Where to start" className="mt-10 grid gap-4 md:grid-cols-3">
        <Entry
          href="/dispatch"
          icon={<PackageCheck className="h-5 w-5" aria-hidden="true" />}
          title="Dispatch planning"
          text="Review the recommended plan, adjust it, and approve it."
          note={planNote(waiting)}
          primary
        />
        <Entry
          href="/forecast"
          icon={<LineChart className="h-5 w-5" aria-hidden="true" />}
          title="Demand forecast"
          text="Expected units per SKU and warehouse, with a likely range."
        />
        <Entry
          href="/kpi"
          icon={<BarChart3 className="h-5 w-5" aria-hidden="true" />}
          title="Forecast accuracy"
          text="How closely predicted demand followed what was really sold."
        />
      </section>
    </div>
  );
}

function Entry({ href, icon, title, text, note, primary }: {
  href: string; icon: React.ReactNode; title: string; text: string; note?: string; primary?: boolean;
}) {
  return (
    <Link href={href}
      className="group flex flex-col rounded-xl border border-surface-line bg-surface p-5 shadow-card transition-shadow hover:shadow-panel">
      <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${primary ? 'bg-primary text-primary-foreground' : 'bg-primary-soft text-primary'}`}>{icon}</span>
      <h2 className="mt-4 text-h4 text-ink-heading">{title}</h2>
      <p className="mt-1 text-body-sm text-ink-muted">{text}</p>
      {note && <p className="mt-3 rounded-md bg-warning-soft px-2.5 py-1.5 text-caption text-warning-text">{note}</p>}
      <span className="mt-auto flex items-center gap-1 pt-4 text-body-sm font-medium text-primary">
        Open <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
      </span>
    </Link>
  );
}
