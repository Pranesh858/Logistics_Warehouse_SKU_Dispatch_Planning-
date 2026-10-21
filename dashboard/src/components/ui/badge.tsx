import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-pill border px-2.5 py-0.5 text-label font-semibold transition-colors',
  {
    variants: {
      variant: {
        default:     'border-transparent bg-primary text-primary-foreground',
        secondary:   'border-surface-line bg-surface-subtle text-ink-body',
        outline:     'border-primary text-primary bg-primary-soft',
        destructive: 'border-transparent bg-destructive text-destructive-foreground',
        success:     'border-success-border bg-success-soft text-success-text',
        warning:     'border-warning-border bg-warning-soft text-warning-text',
        danger:      'border-danger-border bg-danger-soft text-danger-text',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
