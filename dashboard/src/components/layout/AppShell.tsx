'use client';

import { useState } from 'react';
import { Menu } from 'lucide-react';
import { Sidebar } from './Sidebar';

/** Fixed navigation rail on the left, the work on the right. Below 1024px the rail becomes a drawer. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface-page">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-rail lg:block">
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink-heading/50 animate-fade-in" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute inset-y-0 left-0 w-rail animate-panel-in">
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <button type="button" onClick={() => setOpen(true)} aria-label="Open menu"
        className="fixed left-3 top-2.5 z-30 rounded-md border border-surface-rule bg-surface p-2 text-ink-body shadow-panel lg:hidden">
        <Menu className="h-4 w-4" aria-hidden="true" />
      </button>

      <div className="lg:pl-rail">{children}</div>
    </div>
  );
}
