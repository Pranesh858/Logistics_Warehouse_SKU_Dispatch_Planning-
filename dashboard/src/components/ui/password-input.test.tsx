/**
 * The show/hide button on password fields: it must reveal what was typed only when asked, keep the field's own
 * label, and never be mistaken for the form's submit button.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { PasswordInput } from './password-input';

function Form({ onSubmit = () => {}, secretName }: { onSubmit?: () => void; secretName?: string }) {
  const [value, setValue] = useState('');
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
      <label>Password
        <PasswordInput value={value} onChange={(e) => setValue(e.target.value)} secretName={secretName} />
      </label>
      <button type="button" onClick={() => setValue('')}>Clear</button>
    </form>
  );
}

describe('a password field', () => {
  it('hides what is typed until asked to show it', async () => {
    render(<Form />);
    const field = screen.getByLabelText('Password');
    await userEvent.type(field, 'Dispatch@123');
    expect(field).toHaveAttribute('type', 'password');

    await userEvent.click(screen.getByRole('button', { name: 'Show password' }));
    expect(field).toHaveAttribute('type', 'text');
    expect(field).toHaveValue('Dispatch@123');

    await userEvent.click(screen.getByRole('button', { name: 'Hide password' }));
    expect(field).toHaveAttribute('type', 'password');
  });

  it('keeps its label, so the field is still found by "Password"', () => {
    render(<Form />);
    expect(screen.getByLabelText('Password').tagName).toBe('INPUT');
  });

  it('does not submit the form when the eye is pressed', async () => {
    const submit = vi.fn();
    render(<Form onSubmit={submit} />);
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }));
    expect(submit).not.toHaveBeenCalled();
  });

  it('hides again once the field is cleared, so the next password starts hidden', async () => {
    render(<Form />);
    const field = screen.getByLabelText('Password');
    await userEvent.type(field, 'secret-one');
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(field).toHaveAttribute('type', 'password');
  });

  it('names what it hides when it is not a password', () => {
    render(<Form secretName="key" />);
    expect(screen.getByRole('button', { name: 'Show key' })).toBeInTheDocument();
  });
});
