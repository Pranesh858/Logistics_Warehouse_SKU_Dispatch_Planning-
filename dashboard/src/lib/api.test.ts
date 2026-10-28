/**
 * The one function every error banner in the app depends on.
 *
 * The backend says what went wrong in `detail`, and the UI shows that text verbatim rather than inventing
 * its own wording. If this stops unwrapping the message, no test fails anywhere else and no exception is
 * thrown: every error in the product quietly becomes "Something went wrong".
 */
import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { errorMessage } from './api';

function httpError(status: number, data: unknown) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', config, {}, {
    status,
    statusText: '',
    data,
    headers: {},
    config,
  } as never);
}

function networkError() {
  return new AxiosError('Network Error', 'ERR_NETWORK', { headers: new AxiosHeaders() }, {});
}

describe('errorMessage', () => {
  it("shows the backend's own explanation", () => {
    const err = httpError(422, { detail: 'WH03 can only spare 281.5 units of SKU 105 now, not 2777.' });
    expect(errorMessage(err)).toBe('WH03 can only spare 281.5 units of SKU 105 now, not 2777.');
  });

  it('joins up the several complaints a validation error carries', () => {
    const err = httpError(422, { detail: [{ msg: 'qty_ordered must be greater than 0' }, { msg: 'due_date is required' }] });
    expect(errorMessage(err)).toBe('qty_ordered must be greater than 0; due_date is required');
  });

  it('says the backend is unreachable rather than showing an axios message', () => {
    const text = errorMessage(networkError());
    expect(text).toContain('Cannot reach the backend');
    expect(text).toContain('NEXT_PUBLIC_API_URL');
  });

  it('falls back to the error text when there is no detail', () => {
    expect(errorMessage(httpError(500, {}))).toBe('Request failed');
  });

  it('copes with something that is not an error at all', () => {
    expect(errorMessage('a string')).toBe('Something went wrong');
    expect(errorMessage(undefined)).toBe('Something went wrong');
    expect(errorMessage(new Error('plain'))).toBe('plain');
  });
});
