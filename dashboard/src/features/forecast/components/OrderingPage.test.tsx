/**
 * Units to order counts customers already waiting for stock, not only the forecast. The planner has to see why a
 * line is there (the Waiting column) and land on it when Dispatch sends them here for one SKU.
 */
import { screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { forecastApi } from '../api';
import type { OrderRow, OrdersResult } from '../types';
import { OrderingPage } from './OrderingPage';

function row(over: Partial<OrderRow>): OrderRow {
  return {
    product_id: 1, product_name: 'Rice 1kg', category: 'Grocery', warehouse_id: 'WH01', city: 'Chennai',
    lead_time_days: 3, cover_days: 10, period_units: 50, on_order: 0, forecast_units: 70, forecast_high: 80,
    stock_on_hand: 60, reserved: 0, available: 60, days_of_cover: 8.4, waiting: 0, units_to_order: 20,
    priority: 'Order soon', ...over,
  };
}

const RESULT: OrdersResult = {
  days: 7, safety_buffer: true, warehouse_id: null, history_to: '2026-10-31', default_lead_time_days: 3, on_order_units: 0,
  summary: { skus_to_order: 2, units_to_order: 83, order_now: 1, order_soon: 1, forecast_units: 150, skus_checked: 2,
             skus_with_customers_waiting: 1, units_customers_waiting: 63 },
  by_warehouse: [],
  rows: [
    row({ product_id: 38, product_name: 'Floor Cleaner Value 250g', waiting: 63, units_to_order: 63, priority: 'Order now',
          available: 87, days_of_cover: 10.9 }),
    row({}),
  ],
};

beforeEach(() => {
  signInAs('admin');
  vi.spyOn(forecastApi, 'orders').mockResolvedValue(RESULT);
});
afterEach(() => window.history.replaceState(null, '', '/'));

describe('customers waiting on Units to order', () => {
  it('says how many units customers are waiting for and shows them per line', async () => {
    render(<OrderingPage />);
    expect(await screen.findByText(/Customers are waiting for 63 units the shelves cannot fill \(1 product\)/)).toBeInTheDocument();
    const line = screen.getByText('Floor Cleaner Value 250g').closest('tr') as HTMLElement;
    expect(within(line).getByTitle(/customers already ordered/)).toHaveTextContent('63');
    const other = screen.getByText('Rice 1kg').closest('tr') as HTMLElement;
    expect(within(other).queryByTitle(/customers already ordered/)).not.toBeInTheDocument();
  });

  it('opens on the SKU Dispatch sent the planner for', async () => {
    window.history.replaceState(null, '', '/ordering?q=38');
    render(<OrderingPage />);
    expect(await screen.findByText('Floor Cleaner Value 250g')).toBeInTheDocument();
    expect(screen.queryByText('Rice 1kg')).not.toBeInTheDocument();
  });
});
