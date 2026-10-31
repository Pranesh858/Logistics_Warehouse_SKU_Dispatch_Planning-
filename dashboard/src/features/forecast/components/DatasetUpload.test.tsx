/**
 * The "current model was kept" box.
 *
 * "Use it anyway" must repeat what was refused. It used to always repeat an upload, so after a refused
 * "Retrain on current history" it went looking for an uploaded file that did not exist and failed. On a fresh
 * clone, where the history is the 120-day sample, that was the only way to get a retrain through.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, signInAs } from '@/test/render';
import { forecastApi } from '../api';
import type { DatasetStatus } from '../types';
import { DatasetUpload } from './DatasetUpload';

function rejected(over: Partial<DatasetStatus> = {}, sample = false): DatasetStatus {
  return {
    state: 'rejected', reason: 'manual', kind: 'history',
    result: {
      promoted: false, left_out: 0,
      comparison: { wape_before: 0.178, wape_after: 0.221, change_pct: 24.2, worse: true, holdout_days: 28, history_is_sample: sample },
    },
    ...over,
  };
}

beforeEach(() => signInAs('admin'));

describe('after a refused retrain', () => {
  it('retrains on the history again, forced, when the refused run was a history retrain', async () => {
    vi.spyOn(forecastApi, 'datasetStatus').mockResolvedValue(rejected());
    const retrain = vi.spyOn(forecastApi, 'datasetRetrain').mockResolvedValue({ state: 'running' });
    const apply = vi.spyOn(forecastApi, 'datasetApply');
    render(<DatasetUpload />);
    await userEvent.click(await screen.findByRole('button', { name: 'Use the new model anyway' }));
    await waitFor(() => expect(retrain).toHaveBeenCalled());
    expect(retrain.mock.calls[0][0]).toBe(true);
    expect(apply).not.toHaveBeenCalled();
  });

  it('applies the upload again, forced, when the refused run was an upload', async () => {
    vi.spyOn(forecastApi, 'datasetStatus').mockResolvedValue(rejected({ kind: 'upload' }));
    const apply = vi.spyOn(forecastApi, 'datasetApply').mockResolvedValue({ state: 'running' });
    const retrain = vi.spyOn(forecastApi, 'datasetRetrain');
    render(<DatasetUpload />);
    await userEvent.click(await screen.findByRole('button', { name: 'Use the new data anyway' }));
    await waitFor(() => expect(apply).toHaveBeenCalled());
    expect(apply.mock.calls[0][0]).toBe(true);
    expect(retrain).not.toHaveBeenCalled();
  });

  it('says why when the history is only the bundled sample', async () => {
    vi.spyOn(forecastApi, 'datasetStatus').mockResolvedValue(rejected({}, true));
    render(<DatasetUpload />);
    expect(await screen.findByText(/120-day sample that comes with the project/)).toBeInTheDocument();
  });

  it('does not blame the sample when the full history is there', async () => {
    vi.spyOn(forecastApi, 'datasetStatus').mockResolvedValue(rejected());
    render(<DatasetUpload />);
    await screen.findByText('The current model was kept.');
    expect(screen.queryByText(/120-day sample/)).not.toBeInTheDocument();
  });
});
