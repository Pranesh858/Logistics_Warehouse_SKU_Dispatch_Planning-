'use client';

import { cn } from '@/lib/utils';

/**
 * Every page starts the same way: what this is, in a few words, and the controls that act on the whole page.
 * It stays put while the table under it scrolls, so the scope you are working in is never off screen.
 */
export function PageHeader({ title, lead, actions, children, className }: {
  title: string;
  lead?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn('sticky top-0 z-20 border-b border-surface-line bg-surface/95 backdrop-blur', className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 pl-14 lg:px-5 lg:pl-5">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-h2 text-ink-heading">{title}</h1>
          {lead && <p className="mt-0.5 truncate text-caption text-ink-muted">{lead}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2 border-t border-surface-line px-4 py-2 lg:px-5">{children}</div>}
    </header>
  );
}

/** The page's own area. Full width, because the data is the point. */
export function PageBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('px-4 py-4 lg:px-5', className)}>{children}</div>;
}
