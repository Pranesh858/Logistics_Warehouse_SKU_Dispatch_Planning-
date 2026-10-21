'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { LogOut, Truck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useAuth } from '@/features/auth/store';
import { ROLE_LABEL } from '@/features/auth/types';
import { cn } from '@/lib/utils';

const links = [
  { href: '/', label: 'Overview' },
  { href: '/forecast', label: 'Demand forecast' },
  { href: '/dispatch', label: 'Dispatch planning' },
  { href: '/kpi', label: 'Forecast accuracy' },
  { href: '/integrations', label: 'Integrations' },
];

export function Navbar() {
  const pathname = usePathname();
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const items = user?.role === 'admin' ? [...links, { href: '/admin/users', label: 'Users' }] : links;
  const leave = () => { signOut(); qc.clear(); };
  return (
    <header className="sticky top-0 z-30 border-b border-surface-line bg-surface/95 backdrop-blur">
      <nav aria-label="Main" className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Truck className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="text-body font-semibold tracking-tight text-ink-heading">Dispatch Planner</span>
        </Link>

        <ul className="flex items-center gap-1">
          {items.map((l) => {
            const active = l.href === '/' ? pathname === '/' : pathname.startsWith(l.href);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-body-sm font-medium transition-colors',
                    active ? 'bg-primary-soft text-primary' : 'text-ink-muted hover:bg-surface-subtle hover:text-ink-heading',
                  )}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>

        {user && (
          <div className="flex items-center gap-3">
            <Link href="/account" aria-label="Your account and password" title="Your account and password"
              className="hidden rounded-md px-2 py-1 text-right leading-tight transition-colors hover:bg-surface-subtle md:block">
              <div className="text-body-sm font-medium text-ink-heading">{user.name}</div>
              <div className="text-caption text-ink-muted">{user.role === 'admin' ? 'All warehouses' : user.warehouse_id ?? 'All warehouses'}</div>
            </Link>
            <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>{ROLE_LABEL[user.role]}</Badge>
            <button type="button" onClick={leave} aria-label="Sign out" title="Sign out"
              className="rounded-md p-2 text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink-heading">
              <LogOut className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}
      </nav>
    </header>
  );
}
