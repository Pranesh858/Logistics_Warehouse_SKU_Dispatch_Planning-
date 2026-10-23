import { cn } from '@/lib/utils';

/**
 * The instrument cluster. One band divided by hairlines rather than a row of floating cards:
 * these numbers are read together, and a card each would say they are separate things.
 */
export function MetricBand({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('grid grid-cols-2 divide-x divide-y divide-surface-line overflow-hidden rounded-md border border-surface-line bg-surface sm:grid-cols-2 lg:grid-cols-4 lg:divide-y-0', className)}>
      {children}
    </div>
  );
}

const TONE = {
  neutral: 'text-ink-heading',
  good: 'text-success-text',
  warn: 'text-warning-text',
  bad: 'text-danger-text',
} as const;

export function Metric({ label, value, note, tone = 'neutral', action }: {
  label: string;
  value: React.ReactNode;
  note?: React.ReactNode;
  tone?: keyof typeof TONE;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-4 py-3">
      <span className="text-label text-ink-muted">{label}</span>
      <span className={cn('tabular text-metric', TONE[tone])}>{value}</span>
      {note && <span className="truncate text-caption text-ink-subtle">{note}</span>}
      {action && <div className="pt-1.5">{action}</div>}
    </div>
  );
}
