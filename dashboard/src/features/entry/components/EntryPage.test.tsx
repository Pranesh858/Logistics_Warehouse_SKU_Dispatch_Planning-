/**
 * Typing orders and stock in.
 *
 * The risks here are quiet ones: an order saved against the wrong warehouse, a time sent with a zone the
 * backend stores differently, a stock count that says "saved" when nothing changed, and a viewer being
 * handed a form that the server will only refuse afterwards.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { forecastApi } from '@/features/forecast/api';
import type { SkuRow } from '@/features/forecast/types';
import { render, signInAs } from '@/test/render';
import { entryApi } from '../api';
import { defaultDue, EntryPage, localStamp, newOrderId } from './EntryPage';

const SKUS: SkuRow[] = [
  { product_id: 1, warehouse_id: 'WH01', city: 'Pune', category: 'Staples', stock_on_hand: 120 },
  { product_id: 2, warehouse_id: 'WH01', city: 'Pune', category: 'Dairy', stock_on_hand: 40 },
  { product_id: 1, warehouse_id: 'WH02', city: 'Delhi', category: 'Staples', stock_on_hand: 75 },
];

const planWith = (order_id: string, qty_allocated: number) =>
  ({ id: 1, lines: [{ order_id, qty_allocated }] }) as never;

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(forecastApi, 'skus').mockResolvedValue(SKUS);
});

describe('the helpers', () => {
  it('builds order numbers that are recognisable and different each time', () => {
    const a = newOrderId(new Date(2026, 9, 28, 18, 5, 9));
    expect(a).toMatch(/^MAN-261028180509-[0-9A-Z]{2}$/);
    const many = new Set(Array.from({ length: 50 }, () => newOrderId()));
    expect(many.size).toBeGreaterThan(20);
  });

  it('sends local times without a zone, because the backend stores them that way', () => {
    expect(localStamp(new Date(2026, 0, 5, 7, 3, 2))).toBe('2026-01-05T07:03:02');
    expect(defaultDue(new Date(2026, 9, 28, 9, 0))).toBe('2026-10-29T18:00');
    expect(defaultDue(new Date(2026, 11, 31, 23, 0))).toBe('2027-01-01T18:00');
  });
});

describe('who gets the forms', () => {
  it('shows a viewer why there is nothing to fill in', async () => {
    signInAs('viewer');
    render(<EntryPage />);
    expect(await screen.findByText(/view-only access/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save order/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save stock/i })).not.toBeInTheDocument();
  });

  it("fixes a planner to their own warehouse and offers only that warehouse's SKUs", async () => {
    signInAs('planner', 'WH02');
    vi.spyOn(forecastApi, 'skus').mockResolvedValue(SKUS.filter((s) => s.warehouse_id === 'WH02'));
    render(<EntryPage />);
    const wh = (await screen.findAllByLabelText('Warehouse'))[0] as HTMLSelectElement;
    expect(wh.value).toBe('WH02');
    expect(wh).toBeDisabled();
    expect(within(screen.getAllByLabelText('SKU')[0]).getAllByRole('option')).toHaveLength(1);
  });

  it('lists the SKUs of the chosen warehouse, with what is on hand', async () => {
    signInAs('admin');
    render(<EntryPage />);
    const sku = (await screen.findAllByLabelText('SKU'))[0];
    expect(within(sku).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'SKU 1 · Staples · 120 on hand', 'SKU 2 · Dairy · 40 on hand',
    ]);
    await userEvent.selectOptions(screen.getAllByLabelText('Warehouse')[0], 'WH02');
    expect(within(screen.getAllByLabelText('SKU')[0]).getAllByRole('option')).toHaveLength(1);
  });
});

describe('adding an order', () => {
  it('will not save until there is a quantity and a customer', async () => {
    signInAs('admin');
    render(<EntryPage />);
    const save = await screen.findByRole('button', { name: /save order/i });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Units ordered'), '25');
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Customer ID'), 'C-77');
    expect(save).toBeEnabled();
  });

  it('sends the order for the chosen warehouse and SKU, then says how much the plan can fill', async () => {
    signInAs('admin');
    const add = vi.spyOn(entryApi, 'addOrders').mockImplementation(async (orders) => planWith(orders[0].order_id, 60));
    render(<EntryPage />);
    await screen.findByRole('button', { name: /save order/i });
    await userEvent.selectOptions(screen.getAllByLabelText('Warehouse')[0], 'WH01');
    await userEvent.selectOptions(screen.getAllByLabelText('SKU')[0], '2');
    await userEvent.type(screen.getByLabelText('Units ordered'), '100');
    await userEvent.type(screen.getByLabelText('Customer ID'), ' C-77 ');
    await userEvent.selectOptions(screen.getByLabelText('Customer tier'), 'Premium');
    await userEvent.click(screen.getByRole('button', { name: /save order/i }));

    await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
    const sent = add.mock.calls[0][0][0];
    expect(sent).toMatchObject({ product_id: 2, warehouse_id: 'WH01', qty_ordered: 100, customer_id: 'C-77', customer_tier: 'Premium' });
    expect(sent.order_id).toMatch(/^MAN-/);
    expect(sent.order_timestamp).not.toMatch(/Z$|\+/);
    expect(sent.due_date).toMatch(/^\d{4}-\d{2}-\d{2}T18:00:00$/);

    expect(await screen.findByText(/can fill 60 of 100 units/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Units ordered')).toHaveValue(null);           // ready for the next one
  });

  it("says so when the plan can fill the whole order", async () => {
    signInAs('admin');
    vi.spyOn(entryApi, 'addOrders').mockImplementation(async (orders) => planWith(orders[0].order_id, orders[0].qty_ordered));
    render(<EntryPage />);
    await screen.findByRole('button', { name: /save order/i });
    await userEvent.type(screen.getByLabelText('Units ordered'), '10');
    await userEvent.type(screen.getByLabelText('Customer ID'), 'C-1');
    await userEvent.click(screen.getByRole('button', { name: /save order/i }));
    expect(await screen.findByText(/can fill all of it/i)).toBeInTheDocument();
  });

  it("shows the server's reason when it refuses", async () => {
    signInAs('admin');
    vi.spyOn(entryApi, 'addOrders').mockRejectedValue(new Error('SKU 9 does not exist at WH01'));
    render(<EntryPage />);
    await screen.findByRole('button', { name: /save order/i });
    await userEvent.type(screen.getByLabelText('Units ordered'), '10');
    await userEvent.type(screen.getByLabelText('Customer ID'), 'C-1');
    await userEvent.click(screen.getByRole('button', { name: /save order/i }));
    expect(await screen.findByText('SKU 9 does not exist at WH01')).toBeInTheDocument();
  });
});

describe('setting stock', () => {
  it('starts from the number on record, so a change is a correction and not a retype', async () => {
    signInAs('admin');
    render(<EntryPage />);
    expect(await screen.findByLabelText('Units on the shelf now')).toHaveValue(120);
    await userEvent.selectOptions(screen.getAllByLabelText('SKU')[1], '2');
    expect(screen.getByLabelText('Units on the shelf now')).toHaveValue(40);
  });

  it('sends the new count with the reason and reports the change', async () => {
    signInAs('admin');
    const set = vi.spyOn(entryApi, 'setStock').mockResolvedValue({ applied: 1, changed: 1, skipped: 0 });
    render(<EntryPage />);
    const units = await screen.findByLabelText('Units on the shelf now');
    await userEvent.clear(units);
    await userEvent.type(units, '500');
    await userEvent.type(screen.getByLabelText('Reason (optional)'), 'delivery received');
    await userEvent.click(screen.getByRole('button', { name: /save stock/i }));

    await waitFor(() => expect(set).toHaveBeenCalledTimes(1));
    expect(set.mock.calls[0].slice(0, 2)).toEqual([
      [{ product_id: 1, warehouse_id: 'WH01', stock_on_hand: 500 }], 'delivery received',
    ]);
    expect(await screen.findByText(/changed from 120 to 500/i)).toBeInTheDocument();
  });

  it('does not claim a change when the number was already right', async () => {
    signInAs('admin');
    vi.spyOn(entryApi, 'setStock').mockResolvedValue({ applied: 1, changed: 0, skipped: 0 });
    render(<EntryPage />);
    await screen.findByLabelText('Units on the shelf now');
    await userEvent.click(screen.getByRole('button', { name: /save stock/i }));
    expect(await screen.findByText(/nothing changed/i)).toBeInTheDocument();
  });

  it('allows zero, because an empty shelf is a real count', async () => {
    signInAs('admin');
    render(<EntryPage />);
    const units = await screen.findByLabelText('Units on the shelf now');
    await userEvent.clear(units);
    await userEvent.type(units, '0');
    expect(screen.getByRole('button', { name: /save stock/i })).toBeEnabled();
    await userEvent.clear(units);
    expect(screen.getByRole('button', { name: /save stock/i })).toBeDisabled();
  });
});
