import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { createElement } from 'react';
import type { AnchorHTMLAttributes, ReactNode } from 'react';
import { afterEach, vi } from 'vitest';

// Next's router is not running here, and the components that read it only need to know the current path.
// Anything that navigates is tested through what it renders, not through a route change.
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: ReactNode; href: string } & AnchorHTMLAttributes<HTMLAnchorElement>) =>
    createElement('a', { href, ...rest }, children),
}));

// recharts measures its container, which jsdom reports as 0x0, so a chart renders empty and warns. These
// tests are about the numbers and controls around a chart, not the pixels inside it.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) =>
      createElement('div', { style: { width: 800, height: 400 } }, children),
  };
});

afterEach(() => cleanup());
