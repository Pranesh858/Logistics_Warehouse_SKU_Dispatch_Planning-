'use client';

import * as React from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input, type InputProps } from './input';

/**
 * A password (or secret key) field with a button to show what was typed, so a typo can be seen before submitting.
 *
 * `className` sizes and spaces the whole field, as it would on an `Input` (`mt-1`, `w-40`, `h-comp-sm`); the input
 * fills it and the button sits inside its right edge. The text is hidden again whenever the field is cleared,
 * so a new password typed into a form that was just used starts hidden.
 */
export interface PasswordInputProps extends Omit<InputProps, 'type'> {
  /** What the field holds, for the button's label: "Show password", "Show key". */
  secretName?: string;
}

const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, id, value, disabled, secretName = 'password', ...props }, ref) => {
    const [shown, setShown] = React.useState(false);
    const autoId = React.useId();
    const inputId = id ?? autoId;
    React.useEffect(() => {
      if (value === '') setShown(false);
    }, [value]);

    return (
      <span className={cn('relative flex h-comp-md w-full', className)}>
        <Input
          ref={ref}
          id={inputId}
          type={shown ? 'text' : 'password'}
          value={value}
          disabled={disabled}
          className="h-auto min-w-0 flex-1 pr-9"
          {...props}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          disabled={disabled}
          aria-label={`${shown ? 'Hide' : 'Show'} ${secretName}`}
          aria-controls={inputId}
          title={`${shown ? 'Hide' : 'Show'} ${secretName}`}
          className="absolute inset-y-0 right-0 flex w-8 items-center justify-center rounded-r-md text-ink-subtle transition-colors hover:text-ink-heading focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
        >
          {shown ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
        </button>
      </span>
    );
  },
);
PasswordInput.displayName = 'PasswordInput';

export { PasswordInput };
