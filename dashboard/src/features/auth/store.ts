'use client';

import { create } from 'zustand';
import type { AuthUser } from './types';

const KEY = 'dispatch-planner-session';

interface Saved { token: string; user: AuthUser }

function load(): Saved | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Saved) : null;
  } catch {
    return null;
  }
}

function save(s: Saved | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch { /* storage blocked: the session just lasts until the tab closes */ }
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  ready: boolean;                       // saved session has been looked up
  viewWarehouse: string | null;         // admin / viewer: narrow the pages to one warehouse
  hydrate: () => void;
  signIn: (token: string, user: AuthUser) => void;
  signOut: () => void;
  setViewWarehouse: (wh: string | null) => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: null,
  user: null,
  ready: false,
  viewWarehouse: null,
  hydrate: () => {
    const s = load();
    set({ token: s?.token ?? null, user: s?.user ?? null, ready: true });
  },
  signIn: (token, user) => {
    save({ token, user });
    set({ token, user, viewWarehouse: null, ready: true });
  },
  signOut: () => {
    save(null);
    set({ token: null, user: null, viewWarehouse: null });
  },
  setViewWarehouse: (viewWarehouse) => set({ viewWarehouse }),
}));

/** The warehouse the pages are limited to, or null for "all". A planner's own warehouse is enforced by the server. */
export function useScope(): string | null {
  const user = useAuth((s) => s.user);
  const view = useAuth((s) => s.viewWarehouse);
  if (!user) return null;
  return user.role === 'planner' ? user.warehouse_id : view;
}

/** What the signed-in person may do. Viewers read only. */
export function useCan() {
  const user = useAuth((s) => s.user);
  return { edit: !!user && user.role !== 'viewer', admin: user?.role === 'admin', switchWarehouse: !!user && user.role !== 'planner' };
}
