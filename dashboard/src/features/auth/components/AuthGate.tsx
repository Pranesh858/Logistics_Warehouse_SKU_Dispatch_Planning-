'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AppShell } from '@/components/layout/AppShell';
import { useAuth } from '../store';

/** Shows the page only to a signed-in person; everyone else is sent to the sign-in page. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, ready, hydrate } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const onLogin = pathname === '/login';
  const adminOnly = pathname.startsWith('/admin');
  const onAccount = pathname === '/account';
  const mustChange = !!user?.must_change_password;

  useEffect(() => { hydrate(); }, [hydrate]);

  useEffect(() => {
    if (!ready) return;
    if (!user && !onLogin) router.replace('/login');
    else if (user && onLogin) router.replace('/');
    else if (user && mustChange && !onAccount) router.replace('/account');
    else if (user && adminOnly && user.role !== 'admin') router.replace('/');
  }, [ready, user, onLogin, adminOnly, mustChange, onAccount, router]);

  if (!ready) return <div className="min-h-screen bg-surface-page" aria-busy="true" />;
  if (!user) return onLogin ? <main className="min-h-screen bg-surface-page">{children}</main> : null;
  if (onLogin || (adminOnly && user.role !== 'admin') || (mustChange && !onAccount)) return null;

  return (
    <AppShell>
      <main className="min-h-screen">{children}</main>
    </AppShell>
  );
}
