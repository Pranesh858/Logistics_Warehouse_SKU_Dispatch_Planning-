/**
 * What a planner types has to reach the server as the adjustment they meant (+20% is a multiplier of 1.2), and the
 * comparison has to read the right way round: more out-of-stock orders is bad even though the number went up.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { dispatchApi } from '@/features/dispatch/api';
import { forecastApi } from '@/features/forecast/api';
import type { SkuRow } from '@/features/forecast/types';
import { render, signInAs } from '@/test/render';
import { scenariosApi } from '../api';
import type { ScenarioResult, ScenarioSummary } from '../types';
import { ScenariosPage } from './ScenariosPage';

const SKUS: SkuRow[] = [
  { product_id: 1, warehouse_id: 'WH01', city: 'Chennai', category: 'Grocery', stock_on_hand: 100 },
  { product_id: 2, warehouse_id: 'WH02', city: 'Pune', category: 'Dairy', stock_on_hand: 50 },
];

const before: ScenarioSummary = {
  orders: 10, orders_fully_planned: 8, units_ordered: 100, units_planned: 90, fill_rate_pct: 90, order_fill_rate_pct: 80,
  partial: 1, held: 1, backordered: 0, blocked: 0, at_risk: 0,
};

const RESULT: ScenarioResult = {
  warehouse_id: null, plan_version: 12, plan_changes: [], open_orders: 10, before,
  after: { ...before, units_planned: 70, fill_rate_pct: 70, backordered: 2 },
  difference: { units_ordered: 0, units_planned: -20, fill_rate_pct: -20, order_fill_rate_pct: 0, partial: 0, held: 0, backordered: 2, blocked: 0, at_risk: 0 },
};

beforeEach(() => {
  signInAs('admin');
  vi.spyOn(forecastApi, 'skus').mockResolvedValue(SKUS);
  vi.spyOn(dispatchApi, 'warehouses').mockResolvedValue(['WH01', 'WH02']);
});

describe('ScenariosPage', () => {
  it('cannot run with nothing to try', async () => {
    render(<ScenariosPage />);
    expect(screen.getByRole('button', { name: 'Run scenario' })).toBeDisabled();
  });

  it('sends the changes the planner typed', async () => {
    const run = vi.spyOn(scenariosApi, 'run').mockResolvedValue(RESULT);
    render(<ScenariosPage />);
    await screen.findByRole('heading', { name: 'Demand' });
    await waitFor(() => expect(forecastApi.skus).toHaveBeenCalled());
    await waitFor(() => expect(dispatchApi.warehouses).toHaveBeenCalled());
    const [addDemand, addStock, addBlock] = screen.getAllByRole('button', { name: 'Add' });

    await userEvent.click(addDemand);
    await userEvent.selectOptions(await screen.findByLabelText('Category'), 'Dairy');
    await userEvent.click(addStock);
    await userEvent.selectOptions(screen.getAllByLabelText('Warehouse')[1], 'WH02');   // [0] is the page's warehouse switch
    await userEvent.click(addBlock);
    await userEvent.type(screen.getByLabelText('SKU'), '2');
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));

    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][0]).toEqual({
      demand: [{ category: 'Dairy', multiplier: 1.2 }],
      stock: [{ warehouse_id: 'WH02', change_pct: -10 }],
      block: [{ product_id: 2 }],
      warehouse_id: undefined,
    });
  });

  it('compares before and after, and colours by what is good', async () => {
    vi.spyOn(scenariosApi, 'run').mockResolvedValue(RESULT);
    render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));

    const fill = (await screen.findByText('Fill rate')).closest('tr') as HTMLElement;
    expect(within(fill).getByText('90%')).toBeInTheDocument();
    expect(within(fill).getByText('70%')).toBeInTheDocument();
    expect(within(fill).getByText('-20%').className).toContain('danger');
    const out = screen.getByText('Out of stock').closest('tr') as HTMLElement;
    expect(within(out).getByText('+2').className).toContain('danger');         // up, and that is bad
    const held = screen.getByText('Held whole').closest('tr') as HTMLElement;
    expect(within(held).getByText('no change')).toBeInTheDocument();
  });

  it('explains a table of "no change" when every order has already been sent', async () => {
    const run = vi.spyOn(scenariosApi, 'run').mockResolvedValue({ ...RESULT, open_orders: 0 });
    const { unmount } = render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    expect(await screen.findByText(/All 10 orders here have already been sent/)).toBeInTheDocument();
    unmount();

    run.mockResolvedValue(RESULT);
    render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    await screen.findByText('Fill rate');
    expect(screen.queryByText(/already been sent/)).not.toBeInTheDocument();
  });

  it('warns when the current plan is out of date', async () => {
    vi.spyOn(scenariosApi, 'run').mockResolvedValue({ ...RESULT, plan_changes: ['3 new orders'] });
    render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    expect(await screen.findByText(/out of date \(3 new orders\)/)).toBeInTheDocument();
  });

  it("shows the server's reason when it refuses", async () => {
    vi.spyOn(scenariosApi, 'run').mockRejectedValue(new Error('SKU 99 does not exist'));
    render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('SKU 99 does not exist');
  });

  it('keeps a planner to their own warehouse', async () => {
    signInAs('planner', 'WH01');
    const run = vi.spyOn(scenariosApi, 'run').mockResolvedValue(RESULT);
    render(<ScenariosPage />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    const options = within(screen.getByLabelText('Warehouse')).getAllByRole('option');      // a planner has no switch, only this
    expect(options.map((o) => o.textContent)).toEqual(['WH01']);
    await userEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    await waitFor(() => expect(run.mock.calls[0][0].warehouse_id).toBe('WH01'));
  });

  it('is closed to a viewer', () => {
    signInAs('viewer');
    render(<ScenariosPage />);
    expect(screen.getByText('Scenarios are for planners and admins.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run scenario' })).not.toBeInTheDocument();
  });
});
