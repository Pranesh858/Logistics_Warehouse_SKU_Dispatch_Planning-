import { cn } from '@/lib/utils';

/** A titled block of the page. The title line carries the controls that belong to it. */
export function Section({ title, lead, actions, children, className, bare }: {
  title?: string;
  lead?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bare?: boolean;
}) {
  return (
    <section className={cn('space-y-2', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-h3 text-ink-heading">{title}</h2>}
            {lead && <p className="text-caption text-ink-muted">{lead}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {bare ? children : <div>{children}</div>}
    </section>
  );
}

/** A short run of label/value pairs, for a detail panel. */
export function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="divide-y divide-surface-line">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-baseline justify-between gap-3 py-1.5">
          <dt className="text-caption text-ink-muted">{k}</dt>
          <dd className="tabular text-body-sm text-ink-heading">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Something went wrong, said plainly and in place. */
export function Notice({ tone = 'bad', children }: { tone?: 'bad' | 'warn' | 'good' | 'info'; children: React.ReactNode }) {
  const look = {
    bad: 'border-danger-border bg-danger-soft text-danger-text',
    warn: 'border-warning-border bg-warning-soft text-warning-text',
    good: 'border-success-border bg-success-soft text-success-text',
    info: 'border-primary-muted bg-primary-soft text-primary',
  }[tone];
  return (
    <p role={tone === 'bad' ? 'alert' : 'status'} className={cn('rounded-md border px-3 py-2 text-body-sm', look)}>{children}</p>
  );
}
