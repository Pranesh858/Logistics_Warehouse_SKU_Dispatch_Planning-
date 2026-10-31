/**
 * The allocation table: the screen the whole product exists to produce.
 *
 * A planner reads this to decide what ships. The tests below are about the decisions it has to make legible
 * - what was ordered, what the engine would send, and why an order is short - and about the override, which
 * is the one place a person can contradict the engine and must be made to say why.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { dispatchApi } from '../api';
import type { Plan, PlanLine } from '../types';
import { PlanTable } from './PlanTable';

function line(over: Partial<PlanLine> = {}): PlanLine {
  return {
    order_id: 'ORD-1001', order_timestamp: '2026-10-24T08:00:00', customer_id: 'CUST-7',
    customer_tier: 'Premium', product_id: 105, warehouse_id: 'WH02', city: 'Chennai',
    due_date: '2026-10-26T18:00:00', wave_id: 'WH02_2026-10-24',
    qty_ordered: 100, qty_allocated: 100, qty_short: 0, status: 'FULL', at_risk: false,
    rules_applied: 'customer_priority=Premium; inventory_availability',
    exception_type: null, decision: null, override_qty: null, override_reason: null,
    final_qty: 100, send_qty: 100,
    truck_assignments: [{ truck_id: 1, truck_name: 'WH02-T1', qty: 100, manual: false }],
    export_status: null, export_error: null, ...over,
  };
}

function plan(lines: PlanLine[], over: Partial<Plan> = {}): Plan {
  return {
    id: 9, version: 3, status: 'RECOMMENDED', trigger: 'new_orders',
    created_at: '2026-10-24T09:00:00', approved_by: null, approved_at: null,
    summary: {
      orders: lines.length, units_ordered: 0, units_allocated: 0, coverage_pct: 0,
      units_to_send: 0, orders_to_send: 0, units_dispatchable: 0, trucks_used: 1,
      unassigned_orders: 0, exceptions: 0, at_risk: 0, overridden: 0, rejected: 0,
      failed_exports: 0, by_status: {}, by_tier: {},
    },
    lines, trucks: [], unassigned: [], ...over,
  };
}

beforeEach(() => signInAs('planner', 'WH02'));

describe('what the planner reads', () => {
  it('shows an order that could not be filled, in words rather than a code', async () => {
    render(<PlanTable plan={plan([line({
      qty_allocated: 0, qty_short: 100, status: 'BACKORDERED', exception_type: 'Shortage',
      final_qty: 0, send_qty: 0, truck_assignments: [],
    })])} editable />);
    expect(screen.getByText('Out of stock')).toBeInTheDocument();
    expect(screen.queryByText('BACKORDERED')).not.toBeInTheDocument();
    expect(screen.getByText('ORD-1001')).toBeInTheDocument();
  });

  it('translates every allocation outcome the engine can produce', () => {
    const outcomes: [string, string][] = [
      ['FULL', 'Full'], ['PARTIAL', 'Partial'], ['HELD', 'Held whole'],
      ['BACKORDERED', 'Out of stock'], ['BLOCKED', 'Blocked SKU'],
      ['WAVE_OVERFLOW', 'Over wave capacity'], ['COMMITTED', 'Already sent'],
    ];
    render(<PlanTable plan={plan(outcomes.map(([status], i) => line({
      order_id: `ORD-${i}`, status, exception_type: 'Shortage',
    })))} editable />);
    for (const [, label] of outcomes) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('marks an order that will miss its date', () => {
    render(<PlanTable plan={plan([line({ at_risk: true, qty_short: 40, status: 'PARTIAL' })])} editable />);
    expect(screen.getByText('At risk')).toBeInTheDocument();
  });

  it('warns when units are allocated but on no truck, because those do not ship', () => {
    render(<PlanTable plan={plan([line({ truck_assignments: [], send_qty: 0, exception_type: 'Shortage' })])} editable />);
    expect(screen.getByText('No truck')).toBeInTheDocument();
  });

  it('names the truck when there is one', () => {
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable />);
    expect(screen.getByText('WH02-T1')).toBeInTheDocument();
  });

  it('shows how much of a split order each truck carries', () => {
    render(<PlanTable plan={plan([line({
      exception_type: 'Shortage',
      truck_assignments: [
        { truck_id: 1, truck_name: 'WH02-T1', qty: 60, manual: false },
        { truck_id: 2, truck_name: 'WH02-T2', qty: 40, manual: true },
      ],
    })])} editable />);
    expect(screen.getByText('WH02-T1 (60), WH02-T2 (40)')).toBeInTheDocument();
  });
});

describe('the filters', () => {
  it('opens on the orders that need a decision, not on all of them', () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'FINE-1' }),
      line({ order_id: 'SHORT-1', status: 'PARTIAL', qty_short: 30, exception_type: 'Partial Fulfilment' }),
    ])} editable />);
    expect(screen.getByText('SHORT-1')).toBeInTheDocument();
    expect(screen.queryByText('FINE-1')).not.toBeInTheDocument();
    expect(screen.getByText('1 of 2 orders')).toBeInTheDocument();
  });

  it('shows everything when asked', async () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'FINE-1' }),
      line({ order_id: 'SHORT-1', status: 'PARTIAL', exception_type: 'Partial Fulfilment' }),
    ])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'All orders' }));
    expect(screen.getByText('FINE-1')).toBeInTheDocument();
    expect(screen.getByText('2 of 2 orders')).toBeInTheDocument();
  });

  it('narrows to what is actually going out', async () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'GOING', send_qty: 100 }),
      line({ order_id: 'NOT-GOING', send_qty: 0, status: 'BACKORDERED', exception_type: 'Shortage' }),
    ])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Will be sent' }));
    expect(screen.getByText('GOING')).toBeInTheDocument();
    expect(screen.queryByText('NOT-GOING')).not.toBeInTheDocument();
  });

  it('finds an order by SKU or warehouse, not only by order number', async () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'A', product_id: 105, warehouse_id: 'WH02' }),
      line({ order_id: 'B', product_id: 999, warehouse_id: 'WH05' }),
    ])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'All orders' }));
    await userEvent.type(screen.getByLabelText('Search orders'), '999');
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.queryByText('A')).not.toBeInTheDocument();
  });

  it('narrows by customer tier', async () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'PREM', customer_tier: 'Premium' }),
      line({ order_id: 'BASIC', customer_tier: 'Basic' }),
    ])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'All orders' }));
    await userEvent.selectOptions(screen.getByLabelText('Customer tier'), 'Basic');
    expect(screen.getByText('BASIC')).toBeInTheDocument();
    expect(screen.queryByText('PREM')).not.toBeInTheDocument();
  });
});

describe('overriding the engine', () => {
  it('will not save a change without a reason', async () => {
    const review = vi.spyOn(dispatchApi, 'review');
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Change' }));
    await userEvent.clear(screen.getByLabelText(/Units to send/));
    await userEvent.type(screen.getByLabelText(/Units to send/), '60');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(review).not.toHaveBeenCalled();
  });

  it('sends the new quantity and the reason together', async () => {
    const review = vi.spyOn(dispatchApi, 'review').mockResolvedValue(plan([line()]));
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Change' }));
    await userEvent.clear(screen.getByLabelText(/Units to send/));
    await userEvent.type(screen.getByLabelText(/Units to send/), '60');
    await userEvent.type(screen.getByLabelText('Why'), 'customer agreed to a part shipment');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(review).toHaveBeenCalled());
    const [planId, orderId, body] = review.mock.calls[0];
    expect(planId).toBe(9);
    expect(orderId).toBe('ORD-1001');
    expect(body).toEqual({ decision: 'OVERRIDDEN', override_qty: 60, override_reason: 'customer agreed to a part shipment' });
  });

  it('caps the override at what was ordered', async () => {
    render(<PlanTable plan={plan([line({ qty_ordered: 100, exception_type: 'Shortage' })])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Change' }));
    const field = screen.getByLabelText(/Units to send/);
    expect(field).toHaveAttribute('max', '100');
    expect(field).toHaveAttribute('min', '0');
  });

  it('holds an order back', async () => {
    const review = vi.spyOn(dispatchApi, 'review').mockResolvedValue(plan([line()]));
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Hold' }));
    await waitFor(() => expect(review).toHaveBeenCalled());
    expect(review.mock.calls[0][2]).toEqual({ decision: 'REJECTED' });
  });

  it('shows the reason a previous override was given', () => {
    render(<PlanTable plan={plan([line({
      decision: 'OVERRIDDEN', override_qty: 60, override_reason: 'customer agreed to a part shipment',
    })])} editable />);
    expect(screen.getByText(/customer agreed to a part shipment/)).toBeInTheDocument();
    expect(screen.getByText('Changed')).toBeInTheDocument();
  });

  it('explains a refusal from the backend in place', async () => {
    vi.spyOn(dispatchApi, 'review').mockRejectedValue(new Error('Only 40 units are free to allocate'));
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable />);
    await userEvent.click(screen.getByRole('button', { name: 'Hold' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only 40 units are free to allocate');
  });

  it('cannot touch an order that has already gone to the WMS', () => {
    render(<PlanTable plan={plan([line({ status: 'COMMITTED', exception_type: 'Shortage' })])} editable />);
    expect(screen.getByText('Locked')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument();
  });
});

describe('a plan that was already approved', () => {
  it('reports what the WMS did instead of offering changes', () => {
    render(<PlanTable plan={plan([line({ export_status: 'SENT', exception_type: 'Shortage' })],
      { status: 'EXPORTED' })} editable />);
    expect(screen.getByText('Sent', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Sent' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument();
  });

  it('shows why an order did not reach the WMS', () => {
    render(<PlanTable plan={plan([line({
      export_status: 'FAILED', export_error: 'WMS returned 503', exception_type: 'Shortage',
    })], { status: 'PARTIALLY_EXPORTED' })} editable />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText(/WMS returned 503/)).toBeInTheDocument();
  });
});

describe('a read-only view', () => {
  it('shows the plan with nothing to press', () => {
    render(<PlanTable plan={plan([line({ exception_type: 'Shortage' })])} editable={false} />);
    expect(screen.getByText('ORD-1001')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Hold' })).not.toBeInTheDocument();
  });
});

describe('when there is nothing to show', () => {
  it('says so rather than leaving an empty frame', () => {
    render(<PlanTable plan={plan([line({ order_id: 'FINE' })])} editable />);
    expect(screen.getByText('0 of 1 orders')).toBeInTheDocument();
  });
});

describe('dispatch waves', () => {
  it('marks an order carried over from an earlier wave, and only that one', () => {
    render(<PlanTable plan={plan([
      line({ order_id: 'ORD-OLD', carried: true, wave_id: '2026-11-02 Morning' }),
      line({ order_id: 'ORD-NEW', carried: false, wave_id: '2026-11-02 Afternoon' }),
    ])} editable />);
    const badges = screen.getAllByText('Carried over');
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveAttribute('title', 'Placed for the 2026-11-02 Morning wave');
  });
});
