import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

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
    // Playwright specs live in e2e/ and run with their own runner.
    exclude: ['e2e/**', 'node_modules/**', '.next/**'],
  },
});
