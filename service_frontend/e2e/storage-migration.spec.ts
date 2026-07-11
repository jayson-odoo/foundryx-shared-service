import { test } from '@playwright/test';

/**
 * Storage provider migration + centralized Jobs (sprint-4/10, AC-10-22) — E2E
 * against the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real user
 * clicks only (no URL shortcuts).
 *
 * STATUS: STUB — the CODER left the journey outline; the TESTER agent completes
 * + runs it (per the slice-3 brief). See the mock-service Vitest coverage
 * (`hooks/use-storage-migration.test.ts`, `components/platform/jobs-drawer/*`)
 * for the state matrix this exercises end-to-end.
 *
 * Spec-isolation (MANDATORY): storage migration mutates shared storage state, so
 * this MUST provision a DEDICATED tenant (operator API setup is fine; the flow
 * under test stays real clicks). Storage probes stay OFFLINE-deterministic like
 * `integrations.spec.ts` (S3 advanced Endpoint URL → a closed port for a
 * failing-test assertion; a working local/MinIO endpoint for the happy path).
 *
 * Journey to implement:
 *  1. Provision a dedicated tenant via the operator API; sign in (real form).
 *  2. Settings → Integrations → connect an offline-deterministic storage
 *     connection A (S3-compatible, local/MinIO endpoint) + upload an asset that
 *     lands on A (e.g. an avatar or a document) — record it resolves.
 *  3. Open the connection's "…" menu → "Migrate storage" (visible only with
 *     `integrations.migrate_storage`).
 *  4. Wizard step 1: pick the storage provider + fill bucket B config.
 *  5. Wizard step 2: click "Test bucket" → assert Start/Next stays DISABLED
 *     until the test passes; assert the failure reason shows on a bad bucket.
 *  6. Wizard step 3: type the bucket name to confirm → "Start migration".
 *  7. The Jobs drawer opens; poll until the job reaches `done` (progress bar
 *     fills). Open `/jobs/[id]` → assert status Done + zero failures.
 *  8. Assert the PRE-EXISTING asset still resolves (now from B) AND a NEW
 *     upload made after start also resolves from B (both zero 404s, AC-10-21).
 *
 * Verify at 375px AND 1280px (`page.setViewportSize`).
 */

test.fixme('storage migration: connect A → migrate to B → job done → assets resolve', async () => {
  // TODO(tester): implement per the outline above.
});
