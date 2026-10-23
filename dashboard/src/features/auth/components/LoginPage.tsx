'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Truck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/lib/api';
import { authApi } from '../api';
import { useAuth } from '../store';

const DEMO = process.env.NEXT_PUBLIC_DEMO_HINT === 'true';
const DEMO_ACCOUNTS = [
  ['admin', 'Planning admin: every warehouse'],
  ['planner.wh01', 'Planner: warehouse WH01 only'],
  ['planner.wh02', 'Planner: warehouse WH02 only'],
  ['viewer', 'Viewer: read only'],
];

export function LoginPage() {
  const router = useRouter();
  const expired = useSearchParams().get('expired');
  const signIn = useAuth((s) => s.signIn);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await authApi.login(username.trim(), password);
      signIn(res.access_token, res.user);
      router.replace('/');
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6 py-12">
      <div className="mb-5 flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-sm bg-chrome text-white">
          <Truck className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="text-h3 text-ink-heading">Dispatch Planner</span>
      </div>

      <div className="rounded-md border border-surface-line bg-surface">
        <div className="p-5">
          <h1 className="text-h2 text-ink-heading">Sign in</h1>
          <p className="mt-0.5 text-caption text-ink-muted">Use the account your administrator gave you.</p>

          {expired && !error && (
            <p role="status" className="mt-3 rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-body-sm text-warning-text">
              Your session ended. Sign in again to continue.
            </p>
          )}

          <form onSubmit={submit} className="mt-4 space-y-3">
            <label className="block text-label text-ink-muted">Username
              <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required className="mt-1" />
            </label>
            <label className="block text-label text-ink-muted">Password
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required className="mt-1" />
            </label>
            {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy || !username.trim() || !password}>{busy ? 'Signing in…' : 'Sign in'}</Button>
          </form>
        </div>
      </div>

      {DEMO && (
        <div className="mt-4 rounded-md border border-surface-line bg-surface px-4 py-3">
          <p className="text-h4 text-ink-heading">Demo accounts</p>
          <p className="mt-0.5 text-caption text-ink-muted">Pick one to fill the username. The demo password is in the project README.</p>
          <ul className="mt-2 space-y-1">
            {DEMO_ACCOUNTS.map(([u, label]) => (
              <li key={u}>
                <button type="button" onClick={() => setUsername(u)} className="flex w-full items-baseline justify-between gap-3 rounded-md px-2 py-1 text-left text-body-sm hover:bg-surface-subtle">
                  <span className="font-mono text-caption font-medium text-ink-body">{u}</span><span className="text-caption text-ink-muted">{label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
