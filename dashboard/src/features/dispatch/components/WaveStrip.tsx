'use client';

import { Button } from '@/components/ui/button';
import type { Plan, WaveInfo } from '../types';
import { fmt, fmtDay, fmtTime } from './format';

function phase(w: WaveInfo, now: Date): string {
  if (now < new Date(w.cutoff)) return 'Taking orders';
  if (now < new Date(w.departure)) return 'Cut-off passed: review, approve and load';
  return 'Trucks have left';
}

/** Which dispatch wave the plan is for, and what is outside it: orders for later waves, and orders for this
 *  wave that arrived after the plan was built (they join at the next order sync, or now if the planner asks). */
export function WaveStrip({ plan, onUpdate, updating, now = new Date() }: {
  plan: Plan;
  onUpdate?: () => void;      // given only to someone allowed to rebuild the plan
  updating?: boolean;
  now?: Date;
}) {
  const w = plan.wave;
  if (!w) return null;
  const draft = plan.status === 'RECOMMENDED';
  return (
    <div className="space-y-2">
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
      {draft && w.new_since_plan > 0 && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary-muted bg-primary-soft px-3 py-2 text-body-sm text-primary">
          <span>
            {fmt(w.new_since_plan)} new {w.new_since_plan === 1 ? 'order' : 'orders'} for this wave arrived after this plan was built.
            They join at the next order sync{onUpdate ? ', or now if you update the plan' : ''}.
          </span>
          {onUpdate && (
            <Button size="sm" variant="outline" onClick={onUpdate} disabled={updating}>
              {updating ? 'Updating…' : 'Update plan now'}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
