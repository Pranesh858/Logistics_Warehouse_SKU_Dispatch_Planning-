/**
 * The transfers table.
 *
 * Approving one of these moves real stock off a warehouse's shelf, so the things worth testing are the ones
 * that would let somebody do that by accident or not understand what they did: the route and quantity being
 * legible, the right action appearing for the stage a transfer is at, and a lateness being visible.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { dispatchApi } from '../api';
import type { StockTransfer } from '../types';
import { TransfersTable, transferHint } from './TransfersTable';

function transfer(over: Partial<StockTransfer> = {}): StockTransfer {
  return {
    id: 1, transfer_ref: 'TR-WH02-20261024-AB12', product_id: 105,
    from_warehouse_id: 'WH05', to_warehouse_id: 'WH02', qty: 80, transit_days: 2,
    status: 'PROPOSED',
    reason: '80 units short on 3 order(s) at WH02; WH05 can spare 400 and is 2 day(s) away',
    short_orders: 3,
    earliest_due: '2026-11-02T00:00:00',
    eta: '2026-10-26T09:00:00',
    created_at: '2026-10-24T09:00:00',
    approved_by: null, approved_at: null, received_by: null, received_at: null,
    cancelled_by: null, cancel_reason: null, overdue: false, ...over,
  };
}

function serve(rows: StockTransfer[]) {
  return vi.spyOn(dispatchApi, 'transfers').mockResolvedValue(rows);
}

beforeEach(() => signInAs('admin'));

describe('reading a proposal', () => {
  it('shows the route, the quantity and why it was raised', async () => {
    serve([transfer()]);
    render(<TransfersTable editable />);
    expect(await screen.findByText('105')).toBeInTheDocument();
    expect(screen.getByLabelText('WH05 to WH02')).toBeInTheDocument();
    expect(screen.getByText('80')).toBeInTheDocument();
    expect(screen.getByText(/2 days/)).toBeInTheDocument();
    expect(screen.getByText(/80 units short on 3 order\(s\) at WH02/)).toBeInTheDocument();
    expect(screen.getByText('Proposed')).toBeInTheDocument();
  });

  it('says plainly when there is nothing to move', async () => {
    serve([]);
    render(<TransfersTable editable />);
    expect(await screen.findByText(/Nothing to move/)).toBeInTheDocument();
    expect(screen.getByText(/no spare stock elsewhere that would arrive in time/)).toBeInTheDocument();
  });

  it('marks a shipment that should have arrived', async () => {
    serve([transfer({ status: 'IN_TRANSIT', overdue: true })]);
    render(<TransfersTable editable />);
    expect(await screen.findByText('overdue')).toBeInTheDocument();
  });

  it('shows the backend error rather than an empty table', async () => {
    vi.spyOn(dispatchApi, 'transfers').mockRejectedValue(new Error('cannot reach the planner'));
    render(<TransfersTable editable />);
    expect(await screen.findByText('cannot reach the planner')).toBeInTheDocument();
  });
});

describe('the action offered matches the stage', () => {
  it('offers to send a proposal', async () => {
    serve([transfer()]);
    render(<TransfersTable editable />);
    expect(await screen.findByRole('button', { name: /Approve & send/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Mark arrived/ })).not.toBeInTheDocument();
  });

  it('offers to receive something already on its way, not to send it again', async () => {
    serve([transfer({ status: 'IN_TRANSIT' })]);
    render(<TransfersTable editable />);
    expect(await screen.findByRole('button', { name: /Mark arrived/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve & send/ })).not.toBeInTheDocument();
  });

  it('sends the right transfer when approved', async () => {
    const approve = vi.spyOn(dispatchApi, 'approveTransfer').mockResolvedValue(transfer({ status: 'IN_TRANSIT' }));
    serve([transfer({ id: 42 })]);
    render(<TransfersTable editable />);
    await userEvent.click(await screen.findByRole('button', { name: /Approve & send/ }));
    await waitFor(() => expect(approve).toHaveBeenCalled());
    expect(approve.mock.calls[0][0]).toBe(42);
  });

  it('receives the right transfer', async () => {
    const receive = vi.spyOn(dispatchApi, 'receiveTransfer').mockResolvedValue(transfer({ status: 'RECEIVED' }));
    serve([transfer({ id: 7, status: 'IN_TRANSIT' })]);
    render(<TransfersTable editable />);
    await userEvent.click(await screen.findByRole('button', { name: /Mark arrived/ }));
    await waitFor(() => expect(receive).toHaveBeenCalled());
    expect(receive.mock.calls[0][0]).toBe(7);
  });

  it('asks for a reason before cancelling', async () => {
    const cancel = vi.spyOn(dispatchApi, 'cancelTransfer').mockResolvedValue(transfer({ status: 'CANCELLED' }));
    serve([transfer({ id: 9 })]);
    render(<TransfersTable editable />);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    await userEvent.type(screen.getByLabelText(/Why transfer .* is cancelled/), 'lorry broke down');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel it' }));
    await waitFor(() => expect(cancel).toHaveBeenCalled());
    expect(cancel.mock.calls[0].slice(0, 2)).toEqual([9, 'lorry broke down']);
  });

  it('lets you back out of cancelling', async () => {
    const cancel = vi.spyOn(dispatchApi, 'cancelTransfer');
    serve([transfer()]);
    render(<TransfersTable editable />);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }));
    expect(cancel).not.toHaveBeenCalled();
  });

  it('explains a refusal instead of failing quietly', async () => {
    vi.spyOn(dispatchApi, 'approveTransfer')
      .mockRejectedValue(new Error('WH05 can only spare 20 units of SKU 105 now, not 80.'));
    serve([transfer()]);
    render(<TransfersTable editable />);
    await userEvent.click(await screen.findByRole('button', { name: /Approve & send/ }));
    expect(await screen.findByText(/can only spare 20 units/)).toBeInTheDocument();
  });
});

describe('a read-only view', () => {
  it('shows the transfers with nothing to press', async () => {
    serve([transfer()]);
    render(<TransfersTable editable={false} />);
    expect(await screen.findByText('105')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Approve & send/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('tells a viewer who approves one', async () => {
    signInAs('viewer');
    serve([transfer()]);
    render(<TransfersTable editable={false} />);
    expect(await screen.findByText(/a planner or admin approves a transfer/i)).toBeInTheDocument();
  });
});

describe('finished transfers', () => {
  it('are listed separately with who did what', async () => {
    serve([transfer({ id: 3, status: 'RECEIVED', received_by: 'priya', received_at: '2026-10-26T10:00:00' })]);
    render(<TransfersTable editable />);
    expect(await screen.findByText('Received')).toBeInTheDocument();
    expect(screen.getByText(/priya/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing to move/)).toBeInTheDocument();   // nothing outstanding
  });

  it('say why one was cancelled', async () => {
    serve([transfer({ status: 'CANCELLED', cancelled_by: 'admin', cancel_reason: 'no longer needed' })]);
    render(<TransfersTable editable />);
    expect(await screen.findByText('no longer needed')).toBeInTheDocument();
  });
});

describe('the one-line hint on the plan', () => {
  it('stays silent when there is nothing to move', () => {
    expect(transferHint([])).toBeNull();
    expect(transferHint(undefined)).toBeNull();
    expect(transferHint([transfer({ status: 'IN_TRANSIT' })])).toBeNull();
  });

  it('adds up the units and counts the warehouses they would come from', () => {
    const hint = transferHint([
      transfer({ id: 1, qty: 80, from_warehouse_id: 'WH05' }),
      transfer({ id: 2, qty: 40, from_warehouse_id: 'WH01' }),
      transfer({ id: 3, qty: 30, from_warehouse_id: 'WH05' }),
    ]);
    expect(hint).toContain('150');
    expect(hint).toContain('2 other warehouse(s)');
  });
});
