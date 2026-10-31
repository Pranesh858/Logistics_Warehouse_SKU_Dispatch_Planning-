/**
 * The wave strip tells the planner which wave the plan is for and what is deliberately not in it, so a missing
 * order reads as "it is in the next wave" or "it arrived after this plan", not as lost.
 */
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@/test/render';
import type { Plan, WaveInfo } from '../types';
import { WaveStrip } from './WaveStrip';

const morning: WaveInfo = {
  key: '2026-11-02 Morning', name: 'Morning', day: '2026-11-02',
  cutoff: '2026-11-02T09:00:00', departure: '2026-11-02T10:30:00',
  next: { key: '2026-11-02 Afternoon', name: 'Afternoon', day: '2026-11-02', cutoff: '2026-11-02T14:00:00', departure: '2026-11-02T15:30:00' },
  carried_orders: 3, later_wave_orders: 8, new_since_plan: 0,
};

function plan(wave: WaveInfo | null, status: Plan['status'] = 'RECOMMENDED'): Plan {
  return {
    id: 1, version: 4, status, trigger: 'next_wave', created_at: '2026-11-02T08:00:00', approved_by: null, approved_at: null,
    summary: {
      orders: 0, units_ordered: 0, units_allocated: 0, coverage_pct: 0, units_to_send: 0, orders_to_send: 0,
      units_dispatchable: 0, trucks_used: 0, unassigned_orders: 0, exceptions: 0, at_risk: 0, overridden: 0,
      rejected: 0, failed_exports: 0, by_status: {}, by_tier: {},
    },
    lines: [], trucks: [], unassigned: [], wave,
  };
}

describe('WaveStrip', () => {
  it('names the wave, its times and what waits for the next one', () => {
    render(<WaveStrip plan={plan(morning)} now={new Date('2026-11-02T08:00:00')} />);
    expect(screen.getByText(/Morning wave/)).toBeInTheDocument();
    expect(screen.getByText(/Taking orders/)).toBeInTheDocument();
    expect(screen.getByText('8 waiting')).toBeInTheDocument();
    expect(screen.getByText('3 orders')).toBeInTheDocument();
    expect(screen.getByText(/Next: Afternoon/)).toBeInTheDocument();
  });

  it('says when the cut-off has passed and the wave is being loaded', () => {
    render(<WaveStrip plan={plan(morning)} now={new Date('2026-11-02T09:30:00')} />);
    expect(screen.getByText(/Cut-off passed/)).toBeInTheDocument();
  });

  it('offers to bring in orders that arrived after the plan, only to someone who may', async () => {
    const onUpdate = vi.fn();
    const { unmount } = render(<WaveStrip plan={plan({ ...morning, new_since_plan: 2 })} onUpdate={onUpdate} />);
    expect(screen.getByRole('status')).toHaveTextContent('2 new orders for this wave arrived after this plan was built');
    await userEvent.click(screen.getByRole('button', { name: 'Update plan now' }));
    expect(onUpdate).toHaveBeenCalledOnce();
    unmount();

    render(<WaveStrip plan={plan({ ...morning, new_since_plan: 2 })} />);
    expect(screen.queryByRole('button', { name: 'Update plan now' })).not.toBeInTheDocument();
  });

  it('shows nothing when waves are off, and no live counts on an approved plan', () => {
    const { container, unmount } = render(<WaveStrip plan={plan(null)} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    render(<WaveStrip plan={plan(morning, 'EXPORTED')} />);
    expect(screen.getByText(/Morning wave/)).toBeInTheDocument();
    expect(screen.queryByText('8 waiting')).not.toBeInTheDocument();
  });
});
