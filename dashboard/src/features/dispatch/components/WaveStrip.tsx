'use client';

import type { Plan, WaveInfo } from '../types';
import { fmt, fmtDay, fmtTime } from './format';

function phase(w: WaveInfo, now: Date): string {
  if (now < new Date(w.cutoff)) return 'Taking orders';
  if (now < new Date(w.departure)) return 'Cut-off passed: review, approve and load';
  return 'Trucks have left';
}

/** Which dispatch wave the plan is for, and what is outside it: orders carried over and orders for later waves.
 *  Orders that arrived after the plan was built are listed by PlanChanges with everything else that changed. */
export function WaveStrip({ plan, now = new Date() }: { plan: Plan; now?: Date }) {
  const w = plan.wave;
  if (!w) return null;
  const draft = plan.status === 'RECOMMENDED';
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-md border border-surface-line bg-surface px-4 py-2.5">
      <div className="min-w-0">
        <p className="text-body font-medium text-ink-heading">{w.name} wave · {fmtDay(w.cutoff)}</p>
        <p className="text-caption text-ink-muted">
          Orders until {fmtTime(w.cutoff)} · trucks leave {fmtTime(w.departure)}
          {draft && <> · <span className="text-ink-body">{phase(w, now)}</span></>}
        </p>
      </div>
      {draft && (
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-caption">
          <div>
            <dt className="text-ink-muted">Carried over</dt>
            <dd className="tabular text-body-sm text-ink-heading">{fmt(w.carried_orders)} {w.carried_orders === 1 ? 'order' : 'orders'}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Next: {w.next.name}, orders until {fmtTime(w.next.cutoff)}</dt>
            <dd className="tabular text-body-sm text-ink-heading">{fmt(w.later_wave_orders)} waiting</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
