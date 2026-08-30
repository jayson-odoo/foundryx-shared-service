import { defineConfig, devices } from '@playwright/test';

/**
 * LIVE-VERIFY config (plan 22 S2) - drives an ALREADY-RUNNING prod stack.
 *
 * Deliberately has **no `webServer`**. The default config starts `npm run dev`
 * on :3001, and a dev server rewrites `.next` in place - which silently
 * replaces the production build a live verify is supposed to be checking, and
 * then serves 400s for every chunk of the build it just overwrote. A live
 * verify must never build anything.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /s22-live-verify\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.S22_BASE_URL ?? 'http://localhost:3002',
    trace: 'retain-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
