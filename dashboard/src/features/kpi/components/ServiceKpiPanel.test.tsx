/**
 * The panel is read as pass or fail at a glance, so the risks are a wrong tone against the target and a rate shown
 * as 0% when nothing has happened yet.
 */
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { kpiApi } from '../api';
import type { Accuracy, ServiceKpis } from '../types';
import { ServiceKpiPanel } from './ServiceKpiPanel';
import { ServiceTrend } from './ServiceTrend';

const BASE: ServiceKpis = {
  warehouse_id: null, date_from: null, date_to: null, plan_version: 7,
  orders: 40, orders_fully_planned: 30, units_ordered: 1000, units_planned: 960,
  fill_rate_pct: 96, order_fill_rate_pct: 75, partial: 5, held: 3, backordered: 2, blocked: 0, at_risk: 4,
  stock_outs: 2, shipped: 10, shipped_on_time: 9, on_time_pct: 90,
  service_level: { target_pct: 95, measure: 'fill_rate', value_pct: 96, met: true },
  trend: [],
};

const ACCURACY = { target_mape_pct: 20, kpis: { day_mape_pct: 18.4 } } as unknown as Accuracy;

beforeEach(() => {
  signInAs('admin');
  vi.spyOn(kpiApi, 'accuracy').mockResolvedValue(ACCURACY);
});

describe('ServiceKpiPanel', () => {
  it('shows the delivery figures next to the forecast error', async () => {
    vi.spyOn(kpiApi, 'service').mockResolvedValue(BASE);
    render(<ServiceKpiPanel />);
    expect(await screen.findByText('96%')).toBeInTheDocument();
    expect(screen.getByText('meets the target')).toBeInTheDocument();
    expect(screen.getByText('30 of 40')).toBeInTheDocument();
    expect(screen.getByText('9 of 10 shipped')).toBeInTheDocument();
    expect(screen.getByText('Target 95% of ordered units planned. Plan v7.')).toBeInTheDocument();
    expect(await screen.findByText('18.4%')).toBeInTheDocument();
  });

  it('says so when the fill rate is below the target', async () => {
    vi.spyOn(kpiApi, 'service').mockResolvedValue({
      ...BASE, fill_rate_pct: 80, service_level: { ...BASE.service_level, value_pct: 80, met: false },
    });
    render(<ServiceKpiPanel />);
    expect(await screen.findByText('below the target')).toBeInTheDocument();
    expect(screen.getByText('80%').className).toContain('danger');
  });

  it('shows a dash, not 0%, when nothing has been planned or shipped', async () => {
    vi.spyOn(kpiApi, 'service').mockResolvedValue({
      ...BASE, orders: 0, orders_fully_planned: 0, fill_rate_pct: null, order_fill_rate_pct: null, on_time_pct: null,
      shipped: 0, shipped_on_time: 0, stock_outs: 0, at_risk: 0, service_level: { ...BASE.service_level, value_pct: null, met: null },
    });
    render(<ServiceKpiPanel />);
    expect(await screen.findByText('nothing planned')).toBeInTheDocument();
    expect(screen.getByText('nothing shipped yet')).toBeInTheDocument();
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });

  it('asks only for the warehouse being looked at', async () => {
    signInAs('planner', 'WH03');
    const service = vi.spyOn(kpiApi, 'service').mockResolvedValue(BASE);
    render(<ServiceKpiPanel />);
    await waitFor(() => expect(service).toHaveBeenCalledWith('WH03'));
  });

  it("shows the server's reason when it cannot answer", async () => {
    vi.spyOn(kpiApi, 'service').mockRejectedValue(new Error('No plan data'));
    render(<ServiceKpiPanel />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No plan data');
  });
});

describe('ServiceTrend', () => {
  it('says when there is nothing to draw yet', async () => {
    vi.spyOn(kpiApi, 'service').mockResolvedValue(BASE);
    render(<ServiceTrend />);
    expect(await screen.findByText(/Nothing has been approved or shipped/)).toBeInTheDocument();
  });

  it('draws the days that have figures', async () => {
    vi.spyOn(kpiApi, 'service').mockResolvedValue({
      ...BASE, trend: [{ date: '2026-11-01', fill_rate_pct: 90, on_time_pct: null, shipped: 0 }],
    });
    render(<ServiceTrend />);
    expect(await screen.findByRole('img', { name: /fill rate and on-time share/ })).toBeInTheDocument();
  });
});
