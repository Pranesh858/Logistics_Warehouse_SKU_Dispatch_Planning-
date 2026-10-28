import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as rtlRender } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { useAuth } from '@/features/auth/store';
import type { AuthUser, Role } from '@/features/auth/types';

/** A signed-in person. Role and warehouse are what most of the UI branches on. */
export function user(role: Role = 'admin', warehouse_id: string | null = null): AuthUser {
  return {
    id: 1,
    username: role,
    name: role === 'admin' ? 'Admin User' : role === 'planner' ? 'Priya Planner' : 'Vik Viewer',
    role,
    warehouse_id,
    active: true,
    must_change_password: false,
    created_at: '2026-01-01T00:00:00',
    last_login_at: null,
  };
}

export function signInAs(role: Role = 'admin', warehouse_id: string | null = null) {
  useAuth.setState({ token: 'test-token', user: user(role, warehouse_id), ready: true, viewWarehouse: null });
}

export function signOut() {
  useAuth.setState({ token: null, user: null, ready: true, viewWarehouse: null });
}

/**
 * Render with the providers the app supplies in the real tree.
 *
 * Retries are off: a component that is meant to show an error should show it on the first failure, and a
 * test that waits three attempts for that is a slow test about react-query, not about the component.
 */
export function render(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...rtlRender(ui, { wrapper: Wrapper }) };
}
