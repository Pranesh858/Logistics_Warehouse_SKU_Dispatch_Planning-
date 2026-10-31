/**
 * Connecting ERPNext as the ERP. ERPNext signs requests with an API key and a secret, which the planner keeps
 * together as "key:secret"; half of the pair would fail at the first sync, so the form does not save it.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { integrationsApi } from '../api';
import type { SystemSettings } from '../types';
import { ConnectionsCard } from './ConnectionsCard';

function system(system: 'wms' | 'erp', over: Partial<SystemSettings> = {}): SystemSettings {
  return {
    system, kind: 'generic', base_url: '', enabled: false, has_key: false, field_map: {}, sync_minutes: {},
    source: 'app', updated_by: null, updated_at: null, feeds: system === 'wms' ? ['inventory'] : ['orders', 'sales'], ...over,
  };
}

beforeEach(() => signInAs('admin'));

describe('connecting ERPNext', () => {
  it('asks for the key and the secret, and saves them as one key:secret', async () => {
    const save = vi.spyOn(integrationsApi, 'saveSystem').mockResolvedValue(system('erp', { kind: 'erpnext' }));
    render(<ConnectionsCard systems={{ wms: system('wms'), erp: system('erp') }} />);

    await userEvent.selectOptions(screen.getByLabelText('Type of system'), 'erpnext');
    expect(screen.getAllByText(/Field names/)).toHaveLength(1);              // the WMS's; ERPNext is read as it is
    await userEvent.type(screen.getAllByLabelText('Address')[1], 'http://127.0.0.1:8080');
    await userEvent.type(screen.getByLabelText('API key'), 'abc');
    await userEvent.type(screen.getByLabelText('API secret'), 'xyz');
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[1]);

    await waitFor(() => expect(save).toHaveBeenCalled());
    const [which, body] = save.mock.calls[0];
    expect(which).toBe('erp');
    expect(body).toMatchObject({ kind: 'erpnext', base_url: 'http://127.0.0.1:8080', api_key: 'abc:xyz', field_map: {} });
  });

  it('will not save half of the pair', async () => {
    const save = vi.spyOn(integrationsApi, 'saveSystem').mockResolvedValue(system('erp'));
    render(<ConnectionsCard systems={{ wms: system('wms'), erp: system('erp', { kind: 'erpnext' }) }} />);
    await userEvent.type(screen.getByLabelText('API key'), 'abc');
    expect(screen.getByRole('alert')).toHaveTextContent('Enter both the API key and the API secret');
    expect(screen.getAllByRole('button', { name: 'Save' })[1]).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });

  it('keeps the stored pair when nothing is typed, and the WMS has no ERPNext choice', async () => {
    const save = vi.spyOn(integrationsApi, 'saveSystem').mockResolvedValue(system('erp'));
    render(<ConnectionsCard systems={{ wms: system('wms'), erp: system('erp', { kind: 'erpnext', has_key: true }) }} />);
    expect(screen.getAllByLabelText('Type of system')).toHaveLength(1);
    await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[1]);
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1]).toMatchObject({ kind: 'erpnext', api_key: null });
  });
});
