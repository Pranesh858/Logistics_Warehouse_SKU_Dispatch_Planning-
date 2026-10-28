/**
 * The navigation, by role, and the alert count on it.
 *
 * Two things can go wrong here without anything throwing: a planner being shown a page that will refuse
 * them, and the alert count disappearing. The count is the only thing that tells somebody a problem exists
 * without them opening a page, so if it stops rendering the alerts are effectively off.
 */
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { alertsApi } from '@/features/alerts/api';
import type { AlertSummary } from '@/features/alerts/types';
import { render, signInAs } from '@/test/render';
import { Sidebar } from './Sidebar';

const EMPTY: AlertSummary = {
  open: 0, acknowledged: 0, critical: 0, warning: 0, total: 0,
  worst: null, headline: null, enabled: true, channels: [],
};

function summary(over: Partial<AlertSummary> = {}) {
  vi.spyOn(alertsApi, 'summary').mockResolvedValue({ ...EMPTY, ...over });
}

beforeEach(() => summary());

describe('who sees what', () => {
  it('shows an admin the people page', async () => {
    signInAs('admin');
    render(<Sidebar />);
    expect(screen.getByRole('link', { name: /People/ })).toBeInTheDocument();
  });

  it('does not offer a planner a page that would refuse them', () => {
    signInAs('planner', 'WH01');
    render(<Sidebar />);
    expect(screen.queryByRole('link', { name: /People/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Dispatch/ })).toBeInTheDocument();
  });

  it('does not offer a viewer the people page either', () => {
    signInAs('viewer');
    render(<Sidebar />);
    expect(screen.queryByRole('link', { name: /People/ })).not.toBeInTheDocument();
  });

  it('gives everyone the working pages, alerts included', () => {
    signInAs('viewer');
    render(<Sidebar />);
    for (const label of ['Today', 'Dispatch', 'Ordering', 'Forecast', 'Accuracy', 'Alerts']) {
      expect(screen.getByRole('link', { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it('says who is signed in and what they can see', () => {
    signInAs('planner', 'WH02');
    render(<Sidebar />);
    expect(screen.getByText('Priya Planner')).toBeInTheDocument();
    expect(screen.getByText(/Planner · WH02/)).toBeInTheDocument();
  });

  it('shows an admin that they are not limited to one warehouse', () => {
    signInAs('admin');
    render(<Sidebar />);
    expect(screen.getByText(/All warehouses/)).toBeInTheDocument();
  });
});

describe('the alert count', () => {
  it('stays off the screen when nothing is wrong', async () => {
    signInAs('admin');
    render(<Sidebar />);
    await waitFor(() => expect(alertsApi.summary).toHaveBeenCalled());
    expect(screen.queryByLabelText(/need attention/)).not.toBeInTheDocument();
  });

  it('counts what is waiting', async () => {
    summary({ total: 3, warning: 3, open: 3, worst: 'WARNING' });
    signInAs('admin');
    render(<Sidebar />);
    const badge = await screen.findByLabelText('3 alerts need attention');
    expect(badge).toHaveTextContent('3');
  });

  it('turns red when something is costing money now', async () => {
    summary({ total: 2, critical: 1, warning: 1, open: 2, worst: 'CRITICAL' });
    signInAs('admin');
    render(<Sidebar />);
    const badge = await screen.findByLabelText('2 alerts need attention');
    expect(badge.className).toContain('bg-danger');
  });

  it('stays amber when nothing is critical yet', async () => {
    summary({ total: 1, warning: 1, open: 1, worst: 'WARNING' });
    signInAs('admin');
    render(<Sidebar />);
    const badge = await screen.findByLabelText('1 alert need attention');
    expect(badge.className).toContain('bg-warning');
  });

  it('does not grow the rail when the number is large', async () => {
    summary({ total: 240, critical: 240, open: 240, worst: 'CRITICAL' });
    signInAs('admin');
    render(<Sidebar />);
    expect(await screen.findByLabelText('240 alerts need attention')).toHaveTextContent('99+');
  });
});
