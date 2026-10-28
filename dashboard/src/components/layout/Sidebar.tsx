'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity, Bell, ClipboardCheck, LineChart, LogOut, PackagePlus, Plug, ShoppingCart, Truck, Users, X,
} from 'lucide-react';
import { useAlertSummary } from '@/features/alerts/hooks';
import { useAuth } from '@/features/auth/store';
import { ROLE_LABEL } from '@/features/auth/types';
import { cn } from '@/lib/utils';

type Item = { href: string; label: string; icon: React.ReactNode; admin?: boolean; edit?: boolean; badge?: 'alerts' };

const WORK: Item[] = [
  { href: '/', label: 'Today', icon: <ClipboardCheck className="h-4 w-4" /> },
  { href: '/dispatch', label: 'Dispatch', icon: <Truck className="h-4 w-4" /> },
  { href: '/entry', label: 'Orders and stock', icon: <PackagePlus className="h-4 w-4" />, edit: true },
  { href: '/ordering', label: 'Ordering', icon: <ShoppingCart className="h-4 w-4" /> },
  { href: '/forecast', label: 'Forecast', icon: <LineChart className="h-4 w-4" /> },
  { href: '/kpi', label: 'Accuracy', icon: <Activity className="h-4 w-4" /> },
  { href: '/alerts', label: 'Alerts', icon: <Bell className="h-4 w-4" />, badge: 'alerts' },
];

const SETUP: Item[] = [
  { href: '/integrations', label: 'Systems', icon: <Plug className="h-4 w-4" /> },
  { href: '/admin/users', label: 'People', icon: <Users className="h-4 w-4" />, admin: true },
];

/** The dark rail: where you are, where you can go, and who you are signed in as. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const qc = useQueryClient();
  const user = useAuth((s) => s.user);
  const signOut = useAuth((s) => s.signOut);
  const leave = () => { signOut(); qc.clear(); };
  const setup = SETUP.filter((i) => !i.admin || user?.role === 'admin');
  const work = WORK.filter((i) => !i.edit || user?.role !== 'viewer');

  return (
    <div className="flex h-full flex-col bg-chrome text-chrome-text">
      <div className="flex h-topbar items-center gap-2.5 border-b border-chrome-line px-4">
        <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-white/10 text-white">
          <Truck className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="text-body font-semibold tracking-tight text-white">Dispatch Planner</span>
        {onNavigate && (
          <button type="button" onClick={onNavigate} aria-label="Close menu"
            className="ml-auto rounded-sm p-1 text-chrome-text hover:bg-white/10 hover:text-white lg:hidden">
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-3">
        <Group items={work} pathname={pathname} onNavigate={onNavigate} />
        <p className="px-2 pb-1.5 pt-5 text-micro font-medium text-white/35">Setup</p>
        <Group items={setup} pathname={pathname} onNavigate={onNavigate} />
      </nav>

      {user && (
        <div className="border-t border-chrome-line p-2">
          <Link href="/account" onClick={onNavigate}
            className="flex items-center gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-chrome-raised">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-white/10 text-caption font-semibold text-white">
              {user.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-caption font-medium text-white">{user.name}</span>
              <span className="block truncate text-micro text-white/45">
                {ROLE_LABEL[user.role]} · {user.warehouse_id ?? 'All warehouses'}
              </span>
            </span>
          </Link>
          <button type="button" onClick={leave}
            className="mt-0.5 flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-caption text-white/55 transition-colors hover:bg-chrome-raised hover:text-white">
            <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function Group({ items, pathname, onNavigate }: { items: Item[]; pathname: string; onNavigate?: () => void }) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-body-sm transition-colors',
                active ? 'bg-white/[0.09] font-medium text-white' : 'text-chrome-text hover:bg-white/[0.05] hover:text-white',
              )}
            >
              <span className={active ? 'text-white' : 'text-white/45'}>{item.icon}</span>
              {item.label}
              {item.badge === 'alerts' && <AlertCount />}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * How many problems are waiting, on the way in.
 *
 * The count sits in the navigation rather than on the alerts page, because somebody who has to open a page
 * to find out whether anything is wrong will not open it. Red when something is costing money now, amber
 * when something is about to.
 */
function AlertCount() {
  const { data } = useAlertSummary();
  if (!data || data.total === 0) return null;
  const urgent = data.critical > 0;
  return (
    <span
      aria-label={`${data.total} alert${data.total === 1 ? '' : 's'} need attention`}
      className={cn(
        'ml-auto min-w-[1.25rem] rounded-pill px-1.5 py-0.5 text-center text-micro font-semibold tabular',
        urgent ? 'bg-danger text-white' : 'bg-warning text-white',
      )}
    >
      {data.total > 99 ? '99+' : data.total}
    </span>
  );
}
