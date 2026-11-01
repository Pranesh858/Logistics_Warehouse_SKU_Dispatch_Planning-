'use client';

import type { Plan } from '../types';

/** What happened since the plan was built (new orders, stock counts, goods received...). Plans are rebuilt only
 *  when someone presses Generate plan, so this is how the planner knows the one on screen is out of date. */
export function PlanChanges({ plan, canGenerate }: { plan: Plan; canGenerate: boolean }) {
  const changes = plan.changes ?? [];
  if (plan.status !== 'RECOMMENDED' || changes.length === 0) return null;
  const list = changes.map((c) => c.text);
  const said = list.length > 1 ? `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}` : list[0];
  return (
    <div role="status" className="rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-body-sm text-warning-text">
      <strong className="font-medium">This plan is out of date.</strong>{' '}
      Since it was built: {said}.{' '}
      {canGenerate ? 'Press Generate plan to include them.' : 'A planner can generate a new plan to include them.'}
    </div>
  );
}
