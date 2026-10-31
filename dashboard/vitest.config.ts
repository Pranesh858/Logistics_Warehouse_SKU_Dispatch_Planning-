import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The '@/' alias is set here rather than read from tsconfig: the plugin that reads tsconfig is ESM-only and
// this config is loaded as CommonJS. One line beats a dependency that has to be worked around.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
    // Tests mock the API calls they care about. A call they do not mock must fail as if no backend were running,
    // not reach one that happens to be up on localhost:8000: its 401 signs the test user out and breaks the tests
    // after it. Nothing listens on port 9, so such a call is refused straight away.
    env: { NEXT_PUBLIC_API_URL: 'http://127.0.0.1:9' },
  },
});
