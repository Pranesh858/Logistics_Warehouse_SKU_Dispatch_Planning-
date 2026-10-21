import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:     'bg-primary text-primary-foreground hover:bg-primary-hover',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline:     'border border-input bg-surface text-ink-body hover:bg-surface-subtle hover:text-ink-heading',
        secondary:   'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost:       'text-ink-body hover:bg-surface-subtle hover:text-ink-heading',
        link:        'text-primary underline-offset-4 hover:underline p-0 h-auto',
        soft:        'bg-primary-soft text-primary hover:bg-primary-muted',
      },
      size: {
        sm:      'h-comp-sm rounded-md px-3 text-label',
        default: 'h-comp-md rounded-lg px-4 text-body-sm',
        lg:      'h-comp-lg rounded-lg px-6 text-body',
        icon:    'h-comp-md w-comp-md rounded-lg',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
