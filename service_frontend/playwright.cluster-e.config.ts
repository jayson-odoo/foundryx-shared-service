import { defineConfig, devices } from '@playwright/test';

/**
 * Cluster E (AC-06-64) E2E config — runs ONLY `cluster-e-review.spec.ts` against
 * the dedicated live stack: Next prod build on :3002 + FastAPI on :8002
 * (DB `foundryx_service_clustere`, EMS installed, demo seeded). Reuses the already
 * running :3002 server (NEVER boots :3001).
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /cluster-e-review\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 120_000,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3002',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // No webServer block — the :3002 server is already running. (A webServer.url of
  // :3002 with reuseExistingServer also works, but omitting it guarantees we
  // never accidentally boot :3001.)
});
