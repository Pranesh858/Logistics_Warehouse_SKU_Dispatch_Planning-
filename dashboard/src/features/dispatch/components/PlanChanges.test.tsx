/**
 * Plans are rebuilt only when a planner presses Generate plan. The banner is how they learn the plan on screen
 * is missing new orders, a stock count and the like.
 */
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { render } from '@/test/render';
import type { Plan, PlanChange } from '../types';
import { PlanChanges } from './PlanChanges';

function plan(changes: PlanChange[], status: Plan['status'] = 'RECOMMENDED'): Plan {
  return {
    id: 1, version: 7, status, trigger: 'recalculate', created_at: '2026-11-01T10:00:00', approved_by: null, approved_at: null,
    summary: {
      orders: 0, units_ordered: 0, units_allocated: 0, coverage_pct: 0, units_to_send: 0, orders_to_send: 0,
      units_dispatchable: 0, trucks_used: 0, unassigned_orders: 0, exceptions: 0, at_risk: 0, overridden: 0,
      rejected: 0, failed_exports: 0, by_status: {}, by_tier: {},
    },
    lines: [], trucks: [], unassigned: [], changes,
  };
}

const change = (kind: string, text: string, count = 1): PlanChange => ({ kind, count, detail: '', text, at: '2026-11-01T10:05:00' });

describe('PlanChanges', () => {
  it('lists what changed since the plan was built and points at Generate plan', () => {
    render(<PlanChanges plan={plan([change('new_orders', '12 new orders', 12), change('stock_update', 'stock counts changed for 3 SKUs', 3)])} canGenerate />);
    const banner = screen.getByRole('status');
    expect(banner).toHaveTextContent('This plan is out of date');
    expect(banner).toHaveTextContent('Since it was built: 12 new orders and stock counts changed for 3 SKUs.');
    expect(banner).toHaveTextContent('Press Generate plan');
  });

  it('tells a viewer that a planner has to do it', () => {
    render(<PlanChanges plan={plan([change('new_orders', '1 new order')])} canGenerate={false} />);
    expect(screen.getByRole('status')).toHaveTextContent('A planner can generate a new plan');
  });

  it('shows nothing when the plan is up to date or already approved', () => {
    const { container, unmount } = render(<PlanChanges plan={plan([])} canGenerate />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    const r = render(<PlanChanges plan={plan([change('new_orders', '1 new order')], 'EXPORTED')} canGenerate />);
    expect(r.container).toBeEmptyDOMElement();
  });
});
