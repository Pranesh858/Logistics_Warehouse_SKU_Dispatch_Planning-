'use client';

import { useEffect } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Detail without losing your place: the row stays on screen and its detail slides in beside it.
 * This is one of the few things that genuinely floats, so it is one of the few things with a shadow.
 */
export function SidePanel({ title, subtitle, onClose, children, className }: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  return (
    <aside aria-label={title}
      className={cn('flex max-h-[calc(100vh-7rem)] w-full flex-col overflow-hidden rounded-md border border-surface-line bg-surface shadow-panel animate-panel-in xl:sticky xl:top-[7.5rem] xl:w-panel', className)}>
      <div className="flex items-start gap-3 border-b border-surface-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-h3 text-ink-heading">{title}</h2>
          {subtitle && <p className="truncate text-caption text-ink-muted">{subtitle}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="Close"
          className="rounded-sm p-1 text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink-heading">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </aside>
  );
}
