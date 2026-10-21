import { type ClassValue, clsx } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// The custom text sizes (text-body, text-label ...) are font sizes, not colours. Without this,
// tailwind-merge drops the text colour whenever a custom size is on the same element.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: ['tiny', 'label', 'caption', 'body-sm', 'body', 'h4', 'h3', 'h2', 'h1'] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
