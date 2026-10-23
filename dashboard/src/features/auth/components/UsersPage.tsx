'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Empty, Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
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
    <>
      <PageHeader
        title="People"
        lead="A planner works one warehouse. A viewer reads every warehouse and changes nothing. An admin manages these accounts."
      />
      <PageBody className="space-y-4">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2.5 rounded-md border border-surface-line bg-surface px-4 py-3">
          <label className="text-label text-ink-muted">Username
            <Input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 h-comp-sm w-36" required minLength={3} autoComplete="off" />
          </label>
          <label className="text-label text-ink-muted">Full name
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 h-comp-sm w-44" required />
          </label>
          <label className="text-label text-ink-muted">Starting password
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 h-comp-sm w-40"
              required minLength={8} autoComplete="new-password" placeholder="8+ characters" />
          </label>
          <label className="text-label text-ink-muted">Role
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}
              className="mt-1 block h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </label>
          {role !== 'admin' && (
            <label className="text-label text-ink-muted">Warehouse{role === 'viewer' ? ' (optional)' : ''}
              <select value={wh || (needsWh ? whList[0] : '') || ''} onChange={(e) => setWh(e.target.value)}
                className="mt-1 block h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
                {role === 'viewer' && <option value="">All warehouses</option>}
                {whList.map((w) => <option key={w}>{w}</option>)}
              </select>
            </label>
          )}
          <Button type="submit" size="sm" disabled={add.isPending || !username.trim() || !name.trim() || password.length < 8}>Add person</Button>
          <p className="w-full text-caption text-ink-subtle">They must choose their own password the first time they sign in.</p>
        </form>

        {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}

        {users.isLoading ? <p className="py-8 text-center text-body-sm text-ink-muted">Loading…</p>
          : users.isError ? <p role="alert" className="text-body-sm text-danger-text">{errorMessage(users.error)}</p> : (
          <TableFrame>
            <Table>
              <THead>
                <tr><TH>Person</TH><TH>Role</TH><TH>Warehouse</TH><TH>Last sign-in</TH><TH>Status</TH><TH /></tr>
              </THead>
              <tbody>
                {sorted.map((u) => (
                  <TR key={u.id} rail={u.active ? 'none' : 'warn'}>
                    <TD>
                      <span className="block font-medium text-ink-heading">{u.name}</span>
                      <span className="block font-mono text-caption text-ink-subtle">{u.username}</span>
                    </TD>
                    <TD><Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>{ROLE_LABEL[u.role]}</Badge></TD>
                    <TD muted>{u.warehouse_id ?? 'All'}</TD>
                    <TD muted className="whitespace-nowrap">{when(u.last_login_at)}</TD>
                    <TD>
                      <Badge variant={u.active ? 'success' : 'secondary'}>{u.active ? 'Active' : 'Off'}</Badge>
                      {u.must_change_password && <Badge variant="warning" className="ml-1.5">Must set password</Badge>}
                    </TD>
                    <TD align="right">
                      {resetFor === u.id ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Input type="password" aria-label={`New password for ${u.username}`} value={newPw} onChange={(e) => setNewPw(e.target.value)}
                            placeholder="New password" className="h-comp-sm w-36" autoComplete="new-password" />
                          <Button size="sm" disabled={newPw.length < 8 || edit.isPending}
                            onClick={() => change(u, { password: newPw }, () => { setResetFor(null); setNewPw(''); })}>Save</Button>
                          <Button size="sm" variant="ghost" onClick={() => { setResetFor(null); setNewPw(''); }}>Cancel</Button>
                        </span>
                      ) : (
                        <span className="inline-flex gap-1.5">
                          <Button size="sm" variant="outline" onClick={() => { setResetFor(u.id); setNewPw(''); }}>Reset password</Button>
                          {u.id !== me?.id && (
                            <Button size="sm" variant="ghost" disabled={edit.isPending} onClick={() => change(u, { active: !u.active })}>
                              {u.active ? 'Switch off' : 'Switch on'}
                            </Button>
                          )}
                        </span>
                      )}
                    </TD>
                  </TR>
                ))}
                {sorted.length === 0 && <Empty colSpan={6}>No accounts yet.</Empty>}
              </tbody>
            </Table>
          </TableFrame>
        )}
      </PageBody>
    </>
  );
}
