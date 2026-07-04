import { defineConfig, devices } from '@playwright/test';

/**
 * Cluster B (sprint-3/12) E2E config — runs against THIS worktree's live stack
 * (Next dev :3003 → FastAPI :8003 → shared Postgres). No webServer auto-start;
 * reuse the already-running dev server.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: 'ems-cluster-b.spec.ts',
  fullyParallel: false,
  reporter: [['list']],
  timeout: 120_000,
  use: {
    baseURL: 'http://localhost:3003',
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
