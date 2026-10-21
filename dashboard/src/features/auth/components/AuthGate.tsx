'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Navbar } from '@/components/layout/Navbar';
import { useAuth } from '../store';

/** Shows the page only to a signed-in person; everyone else is sent to the sign-in page. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, ready, hydrate } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const onLogin = pathname === '/login';
  const adminOnly = pathname.startsWith('/admin');

  useEffect(() => { hydrate(); }, [hydrate]);

  useEffect(() => {
    if (!ready) return;
    if (!user && !onLogin) router.replace('/login');
    else if (user && onLogin) router.replace('/');
    else if (user && adminOnly && user.role !== 'admin') router.replace('/');
  }, [ready, user, onLogin, adminOnly, router]);

  if (!ready) return <div className="min-h-screen bg-surface-page" aria-busy="true" />;
  if (!user) return onLogin ? <main className="min-h-screen bg-surface-page">{children}</main> : null;
  if (onLogin || (adminOnly && user.role !== 'admin')) return null;

  return (
    <>
      <Navbar />
      <main className="min-h-[calc(100vh-3.5rem)] bg-surface-page">{children}</main>
    </>
  );
}
