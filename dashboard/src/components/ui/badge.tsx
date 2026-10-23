import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/** A state, said in a word and marked with a square. Never colour on its own. */
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-micro font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default:     'border-primary-muted bg-primary-soft text-primary',
        secondary:   'border-surface-line bg-surface-subtle text-ink-muted',
        outline:     'border-surface-rule bg-transparent text-ink-body',
        destructive: 'border-danger-border bg-danger-soft text-danger-text',
        success:     'border-success-border bg-success-soft text-success-text',
        warning:     'border-warning-border bg-warning-soft text-warning-text',
        danger:      'border-danger-border bg-danger-soft text-danger-text',
      },
      dot: { true: '', false: '' },
    },
    defaultVariants: { variant: 'default', dot: true },
  },
);

const DOT: Record<string, string> = {
  default: 'bg-primary', secondary: 'bg-ink-subtle', outline: 'bg-ink-subtle',
  destructive: 'bg-danger', success: 'bg-success', warning: 'bg-warning', danger: 'bg-danger',
};

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, dot = true, children, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && <span aria-hidden="true" className={cn('h-1.5 w-1.5 rounded-[1px]', DOT[variant ?? 'default'])} />}
      {children}
    </div>
  );
}

export { Badge, badgeVariants };
