import { cn } from '@/lib/utils';

/**
 * Dense table. A single outer rule and hairlines between rows: no card, no shadow, no zebra.
 * The header stays while the body scrolls, because a planner reads far down these lists.
 */
export function TableFrame({ children, className, scroll = true }: {
  children: React.ReactNode; className?: string; scroll?: boolean;
}) {
  return (
    <div className={cn('overflow-hidden rounded-md border border-surface-line bg-surface', className)}>
      <div className={cn(scroll && 'overflow-x-auto')}>{children}</div>
    </div>
  );
}

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return <table className={cn('w-full border-collapse text-body-sm', className)}>{children}</table>;
}

export function THead({ children }: { children: React.ReactNode }) {
  return <thead className="sticky top-0 z-10 bg-surface-muted">{children}</thead>;
}

export function TH({ children, align = 'left', className, ...rest }: {
  children?: React.ReactNode; align?: 'left' | 'right' | 'center'; className?: string;
} & React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        'whitespace-nowrap border-b border-surface-line px-3 py-2 text-label font-medium text-ink-muted',
        align === 'right' && 'text-right', align === 'center' && 'text-center', align === 'left' && 'text-left',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

const RAIL = {
  none: undefined,
  good: '#0E7C5A',
  warn: '#B4690E',
  bad: '#C13A2E',
  info: '#1F4B8E',
} as const;

export type Rail = keyof typeof RAIL;

export function TR({ children, rail = 'none', selected, onClick, className }: {
  children: React.ReactNode;
  rail?: Rail;
  selected?: boolean;
  onClick?: () => void;
  className?: string;
}) {
  return (
    <tr
      onClick={onClick}
      aria-selected={selected}
      style={RAIL[rail] ? ({ '--rail': RAIL[rail] } as React.CSSProperties) : undefined}
      className={cn(
        'border-b border-surface-line last:border-0',
        RAIL[rail] && 'state-rail',
        selected && 'bg-primary-soft',
        onClick && 'cursor-pointer hover:bg-surface-muted',
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TD({ children, align = 'left', mono, strong, muted, className, ...rest }: {
  children?: React.ReactNode;
  align?: 'left' | 'right' | 'center';
  mono?: boolean;
  strong?: boolean;
  muted?: boolean;
  className?: string;
} & React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        'px-3 py-1.5 text-ink-body',
        align === 'right' && 'text-right', align === 'center' && 'text-center',
        mono && 'font-mono text-caption',
        strong && 'font-medium text-ink-heading',
        muted && 'text-ink-muted',
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}

/** Nothing to show, and what to do about it. */
export function Empty({ children, colSpan }: { children: React.ReactNode; colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-3 py-10 text-center text-body-sm text-ink-muted">{children}</td>
    </tr>
  );
}
