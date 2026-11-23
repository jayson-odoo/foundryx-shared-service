import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Snapshots and date assertions are recorded in UTC (the CI runner's zone).
// Pin it here, before any worker starts, so a run on a machine in another
// zone (UTC+8 here) renders the same dates instead of failing on them.
process.env.TZ = 'UTC';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // tsconfig maps `@/*` to both `./*` and `./app/components/*`; a vite alias is
      // a single prefix replace, so name the app/components-only prefix first.
      '@/partials': resolve(__dirname, 'app/components/partials'),
      '@': resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    exclude: ['node_modules/**', '.next/**'],
  },
});
