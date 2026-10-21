'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/lib/api';
import { useWarehouseList } from '@/features/dispatch/hooks';
import { useAddUser, useEditUser, useUsers } from '../hooks';
import { useAuth } from '../store';
import { ROLE_LABEL, type AuthUser, type Role } from '../types';

const when = (iso: string | null) => (iso ? new Date(iso + 'Z').toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'Never');

export function UsersPage() {
  const me = useAuth((s) => s.user);
  const users = useUsers();
  const warehouses = useWarehouseList();
  const add = useAddUser();
  const edit = useEditUser();
  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<Role>('planner');
  const [wh, setWh] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPw, setNewPw] = useState('');

  const whList = warehouses.data ?? [];
  const needsWh = role === 'planner';
  const fail = (e: unknown) => setError(errorMessage(e));
  const sorted = useMemo(() => users.data ?? [], [users.data]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    add.mutate(
      { username: username.trim(), name: name.trim(), password, role, warehouse_id: role === 'admin' ? null : (wh || (needsWh ? whList[0] : null) || null) },
      { onSuccess: () => { setUsername(''); setName(''); setPassword(''); }, onError: fail },
    );
  };

  const change = (u: AuthUser, body: Parameters<typeof edit.mutate>[0]['body'], after?: () => void) => {
    setError(null);
    edit.mutate({ id: u.id, body }, { onSuccess: after, onError: fail });
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <header>
        <h1 className="text-[1.5rem] font-semibold tracking-tight text-ink-heading">Users and access</h1>
        <p className="mt-1 max-w-2xl text-body-sm text-ink-muted">
          A planner works on one warehouse only. A viewer can read every warehouse but change nothing. An admin sees everything and manages these accounts.
        </p>
      </header>

      <Card>
        <CardContent className="pt-5">
          <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            <label className="text-label text-ink-muted">Username
              <Input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-40" required minLength={3} autoComplete="off" />
            </label>
            <label className="text-label text-ink-muted">Full name
              <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-48" required />
            </label>
            <label className="text-label text-ink-muted">Password (8+ characters)
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-44" required minLength={8} autoComplete="new-password" />
            </label>
            <label className="text-label text-ink-muted">Role
              <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="mt-1 block h-9 rounded-md border border-input bg-surface px-2 text-body-sm">
                {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </label>
            {role !== 'admin' && (
              <label className="text-label text-ink-muted">Warehouse{role === 'viewer' ? ' (optional)' : ''}
                <select value={wh || (needsWh ? whList[0] : '') || ''} onChange={(e) => setWh(e.target.value)} className="mt-1 block h-9 rounded-md border border-input bg-surface px-2 text-body-sm">
                  {role === 'viewer' && <option value="">All warehouses</option>}
                  {whList.map((w) => <option key={w}>{w}</option>)}
                </select>
              </label>
            )}
            <Button type="submit" disabled={add.isPending || !username.trim() || !name.trim() || password.length < 8}>Add user</Button>
          </form>
          {error && <p role="alert" className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="overflow-x-auto pt-5">
          {users.isLoading ? <p className="text-ink-muted">Loading users…</p> : users.isError ? (
            <p role="alert" className="text-danger-text">{errorMessage(users.error)}</p>
          ) : (
            <table className="w-full text-body-sm">
              <thead><tr className="border-b border-surface-line text-left text-label text-ink-muted">
                <th className="py-2 pr-3">User</th><th className="pr-3">Role</th><th className="pr-3">Warehouse</th>
                <th className="pr-3">Last sign-in</th><th className="pr-3">Status</th><th />
              </tr></thead>
              <tbody>
                {sorted.map((u) => (
                  <tr key={u.id} className="border-b border-surface-line align-top">
                    <td className="py-2 pr-3"><div className="font-medium text-ink-heading">{u.name}</div><div className="text-caption text-ink-muted">{u.username}</div></td>
                    <td className="pr-3 py-2"><Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>{ROLE_LABEL[u.role]}</Badge></td>
                    <td className="pr-3 py-2 text-ink-body">{u.warehouse_id ?? 'All'}</td>
                    <td className="pr-3 py-2 text-ink-muted">{when(u.last_login_at)}</td>
                    <td className="pr-3 py-2"><Badge variant={u.active ? 'success' : 'secondary'}>{u.active ? 'Active' : 'Switched off'}</Badge></td>
                    <td className="py-2 text-right">
                      {resetFor === u.id ? (
                        <span className="inline-flex items-center gap-2">
                          <Input type="password" aria-label={`New password for ${u.username}`} value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="New password" className="h-8 w-40" autoComplete="new-password" />
                          <Button size="sm" disabled={newPw.length < 8 || edit.isPending} onClick={() => change(u, { password: newPw }, () => { setResetFor(null); setNewPw(''); })}>Save</Button>
                          <Button size="sm" variant="ghost" onClick={() => { setResetFor(null); setNewPw(''); }}>Cancel</Button>
                        </span>
                      ) : (
                        <span className="inline-flex gap-2">
                          <Button size="sm" variant="outline" onClick={() => { setResetFor(u.id); setNewPw(''); }}>Reset password</Button>
                          {u.id !== me?.id && (
                            <Button size="sm" variant={u.active ? 'ghost' : 'outline'} disabled={edit.isPending} onClick={() => change(u, { active: !u.active })}>
                              {u.active ? 'Switch off' : 'Switch on'}
                            </Button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
