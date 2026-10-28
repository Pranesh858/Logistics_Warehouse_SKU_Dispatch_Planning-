/**
 * The alerts page.
 *
 * What is worth testing is not that rows appear, it is the promises the page makes about them: worst first,
 * acknowledging does not make a problem disappear, closing one asks why, and a viewer is given nothing to
 * press. Each of those can break silently.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { alertsApi } from '../api';
import type { Alert, AlertSummary } from '../types';
import { AlertsPage } from './AlertsPage';

const SUMMARY: AlertSummary = {
  open: 2, acknowledged: 0, critical: 1, warning: 1, total: 2,
  worst: 'CRITICAL', headline: 'Out of stock', enabled: true, channels: [],
};

function alert(over: Partial<Alert> = {}): Alert {
  return {
    id: 1, kind: 'stockout', severity: 'CRITICAL', status: 'OPEN',
    title: 'Wheat Flour Premium is out of stock at WH03',
    detail: 'Nothing free to sell, and 420 units are forecast over the next 10 days.',
    warehouse_id: 'WH03', product_id: 1, occurrences: 1,
    first_seen: new Date(Date.now() - 20 * 60_000).toISOString(),
    last_seen: new Date(Date.now() - 20 * 60_000).toISOString(),
    acknowledged_by: null, acknowledged_at: null, resolved_at: null, resolved_note: null,
    delivery: null, ...over,
  };
}

function serve(alerts: Alert[], over: Partial<AlertSummary> = {}) {
  const summary = vi.spyOn(alertsApi, 'summary').mockResolvedValue({ ...SUMMARY, total: alerts.length, ...over });
  const list = vi.spyOn(alertsApi, 'list').mockResolvedValue(alerts);
  return { summary, list };
}

beforeEach(() => signInAs('admin'));

describe('the list', () => {
  it('shows what is wrong and what to do about it', async () => {
    serve([alert()]);
    render(<AlertsPage />);
    expect(await screen.findByText(/Wheat Flour Premium is out of stock at WH03/)).toBeInTheDocument();
    expect(screen.getByText(/420 units are forecast/)).toBeInTheDocument();
    expect(screen.getByText('WH03')).toBeInTheDocument();
    expect(screen.getByText('Out of stock')).toBeInTheDocument();
  });

  it('puts the worst first, in the order the backend sent', async () => {
    serve([
      alert({ id: 1, severity: 'CRITICAL', title: 'Out of stock at WH03' }),
      alert({ id: 2, severity: 'WARNING', kind: 'low_cover', title: 'Runs out in 2 days at WH01' }),
      alert({ id: 3, severity: 'INFO', kind: 'retrain_done', title: 'A new forecast model is live' }),
    ]);
    render(<AlertsPage />);
    await screen.findByText('Out of stock at WH03');
    const items = screen.getAllByRole('listitem').map((li) => li.textContent ?? '');
    expect(items[0]).toContain('Out of stock at WH03');
    expect(items[1]).toContain('Runs out in 2 days at WH01');
    expect(items[2]).toContain('A new forecast model is live');
  });

  it('says how long a problem has been going and how often it has been seen', async () => {
    serve([alert({ occurrences: 7 })]);
    render(<AlertsPage />);
    expect(await screen.findByText(/20 min ago/)).toBeInTheDocument();
    expect(screen.getByText(/seen 7 times/)).toBeInTheDocument();
  });

  it('does not say "seen once"', async () => {
    serve([alert({ occurrences: 1 })]);
    render(<AlertsPage />);
    await screen.findByText(/out of stock/);
    expect(screen.queryByText(/seen 1 times/)).not.toBeInTheDocument();
  });

  it('says plainly when nothing needs attention', async () => {
    serve([], { total: 0, open: 0, critical: 0, warning: 0, worst: null, headline: null });
    render(<AlertsPage />);
    expect(await screen.findByText(/are all being watched/)).toBeInTheDocument();
    expect(screen.getAllByText('Nothing needs attention.').length).toBeGreaterThan(0);
  });

  it('counts the alerts by how much they matter', async () => {
    serve([alert(), alert({ id: 2, severity: 'WARNING', kind: 'low_cover', title: 'Basmati Rice runs out in 2 days' })],
          { critical: 1, warning: 1, open: 2, acknowledged: 0 });
    render(<AlertsPage />);
    await screen.findByText('Basmati Rice runs out in 2 days');
    expect(screen.getByText('Critical').parentElement).toHaveTextContent('1');
    expect(screen.getByText('Warnings').parentElement).toHaveTextContent('1');
  });

  it('shows the backend error rather than an empty page', async () => {
    vi.spyOn(alertsApi, 'summary').mockResolvedValue(SUMMARY);
    vi.spyOn(alertsApi, 'list').mockRejectedValue(new Error('the database is down'));
    render(<AlertsPage />);
    expect(await screen.findByText('the database is down')).toBeInTheDocument();
  });
});

describe('acting on one', () => {
  it('acknowledging says somebody is on it without hiding the problem', async () => {
    const ack = vi.spyOn(alertsApi, 'acknowledge').mockResolvedValue(alert({ status: 'ACKNOWLEDGED' }));
    serve([alert()]);
    render(<AlertsPage />);
    await userEvent.click(await screen.findByRole('button', { name: /I’m on it/ }));
    await waitFor(() => expect(ack).toHaveBeenCalled());
    expect(ack.mock.calls[0][0]).toBe(1);
    expect(screen.getByText(/out of stock/)).toBeInTheDocument();
  });

  it('offers nothing to acknowledge on an alert somebody already picked up', async () => {
    serve([alert({ status: 'ACKNOWLEDGED', acknowledged_by: 'priya' })]);
    render(<AlertsPage />);
    await screen.findByText(/out of stock/);
    expect(screen.queryByRole('button', { name: /I’m on it/ })).not.toBeInTheDocument();
    expect(screen.getByText(/priya is on it/)).toBeInTheDocument();
  });

  it('asks why before closing one, and warns that closing is not fixing', async () => {
    const resolve = vi.spyOn(alertsApi, 'resolve').mockResolvedValue(alert({ status: 'RESOLVED' }));
    serve([alert()]);
    render(<AlertsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Close' }));
    expect(screen.getByText(/the next check raises it again/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Why this alert is being closed/), 'stock was miscounted');
    await userEvent.click(screen.getByRole('button', { name: 'Close it' }));
    await waitFor(() => expect(resolve).toHaveBeenCalled());
    expect(resolve.mock.calls[0].slice(0, 2)).toEqual([1, 'stock was miscounted']);
  });

  it('lets you change your mind about closing', async () => {
    const resolve = vi.spyOn(alertsApi, 'resolve');
    serve([alert()]);
    render(<AlertsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Close' }));
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }));
    expect(screen.queryByLabelText(/Why this alert is being closed/)).not.toBeInTheDocument();
    expect(resolve).not.toHaveBeenCalled();
  });

  it('shows why an action was refused', async () => {
    vi.spyOn(alertsApi, 'acknowledge').mockRejectedValue(new Error('This alert is already acknowledged'));
    serve([alert()]);
    render(<AlertsPage />);
    await userEvent.click(await screen.findByRole('button', { name: /I’m on it/ }));
    expect(await screen.findByText('This alert is already acknowledged')).toBeInTheDocument();
  });
});

describe('what a viewer gets', () => {
  it('can read the alerts but is offered nothing to press', async () => {
    signInAs('viewer');
    serve([alert()]);
    render(<AlertsPage />);
    await screen.findByText(/out of stock/);
    expect(screen.queryByRole('button', { name: /I’m on it/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check now' })).not.toBeInTheDocument();
  });
});

describe('delivery', () => {
  it('says alerts are in-app only until a channel is configured', async () => {
    serve([alert()]);
    render(<AlertsPage />);
    expect(await screen.findByText(/Alerts appear here only/)).toBeInTheDocument();
  });

  it('names the channels once they are set, and lets an admin test them', async () => {
    const test = vi.spyOn(alertsApi, 'testDelivery')
      .mockResolvedValue({ channels: ['webhook'], ok: true, message: 'Test alert sent.' });
    serve([alert()], { channels: ['webhook', 'email'] });
    render(<AlertsPage />);
    expect(await screen.findByText(/Also pushed to: webhook and email/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Send a test/ }));
    await waitFor(() => expect(test).toHaveBeenCalled());
  });

  it('does not offer the delivery test to a planner', async () => {
    signInAs('planner', 'WH03');
    serve([alert()], { channels: ['webhook'] });
    render(<AlertsPage />);
    await screen.findByText(/Also pushed to/);
    expect(screen.queryByRole('button', { name: /Send a test/ })).not.toBeInTheDocument();
  });

  it('warns when alerts are switched off altogether', async () => {
    serve([], { enabled: false, total: 0 });
    render(<AlertsPage />);
    expect(await screen.findByText(/Alerts are switched off/)).toBeInTheDocument();
  });
});

describe('closed alerts', () => {
  it('can be looked at without mixing them into the live list', async () => {
    const { list } = serve([alert()]);
    render(<AlertsPage />);
    await screen.findByText(/out of stock/);
    await userEvent.click(screen.getByRole('button', { name: 'Recently closed' }));
    await waitFor(() => expect(list).toHaveBeenCalledWith(null, 'RESOLVED'));
    expect(screen.getByRole('button', { name: 'Back to live' })).toBeInTheDocument();
  });

  it('offers no actions on something already closed', async () => {
    serve([alert({ status: 'RESOLVED', resolved_note: 'stock arrived' })]);
    render(<AlertsPage />);
    await screen.findByText(/out of stock/);
    await userEvent.click(screen.getByRole('button', { name: 'Recently closed' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument());
  });
});
