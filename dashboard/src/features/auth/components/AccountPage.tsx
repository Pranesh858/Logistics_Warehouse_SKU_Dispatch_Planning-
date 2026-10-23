'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/lib/api';
import { authApi } from '../api';
import { useAuth } from '../store';
import { ROLE_LABEL } from '../types';

export function AccountPage() {
  const user = useAuth((s) => s.user);
  const signIn = useAuth((s) => s.signIn);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (!user) return null;
  const mustChange = !!user.must_change_password;
  const tooShort = next.length > 0 && next.length < 8;
  const mismatch = again.length > 0 && again !== next;
  const ready = current && next.length >= 8 && again === next && next !== current;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const res = await authApi.changePassword(current, next);
      signIn(res.access_token, res.user);          // other sign-ins end; this one carries on with a fresh token
      setCurrent(''); setNext(''); setAgain('');
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Your account" lead={`${user.name} · ${user.username} · ${ROLE_LABEL[user.role]}${user.warehouse_id ? ` · ${user.warehouse_id}` : ''}`} />
      <PageBody className="max-w-lg space-y-4">
        {mustChange && (
          <p role="alert" className="rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-body-sm text-warning-text">
            This password was set by someone else. Choose your own to start using the planner.
          </p>
        )}

        <div className="rounded-md border border-surface-line bg-surface">
          <header className="border-b border-surface-line px-4 py-2.5">
            <h2 className="text-h3 text-ink-heading">Change password</h2>
            <p className="text-caption text-ink-muted">At least 8 characters. Changing it ends your other sign-ins.</p>
          </header>

          <form onSubmit={submit} className="space-y-3 p-4">
            <label className="block text-label text-ink-muted">Current password
              <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required className="mt-1" />
            </label>
            <label className="block text-label text-ink-muted">New password
              <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required minLength={8} className="mt-1" />
              {tooShort && <span className="mt-1 block text-caption text-danger-text">Use at least 8 characters.</span>}
            </label>
            <label className="block text-label text-ink-muted">Repeat the new password
              <Input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required className="mt-1" />
              {mismatch && <span className="mt-1 block text-caption text-danger-text">The two passwords do not match.</span>}
            </label>
            {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}
            {done && <p role="status" className="rounded-md border border-success-border bg-success-soft px-3 py-2 text-body-sm text-success-text">Password changed. Your other sign-ins have ended.</p>}
            <Button type="submit" size="sm" disabled={busy || !ready}>{busy ? 'Saving…' : 'Change password'}</Button>
          </form>
        </div>
      </PageBody>
    </>
  );
}
