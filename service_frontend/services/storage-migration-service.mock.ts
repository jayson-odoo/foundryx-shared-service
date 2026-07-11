/**
 * PHASE 1 MOCK storage-migration service (sprint-4/10) — lets the wizard iterate
 * its Test-gated Start flow with NO backend. `testBucket` is tunable via
 * `setMockTestOutcome` (pass/fail). `startMigration` returns a fresh running job.
 *
 * DEBT: shipped boundary is `.real`; this exists for frontend-first + Vitest.
 */
import type {
  Job,
  StorageMigrationStartInput,
  StorageMigrationTestInput,
  StorageMigrationTestResult,
} from '@/types/jobs';
import type { StorageMigrationService } from './storage-migration-service';

const delay = <T>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 80));

let _testOutcome: StorageMigrationTestResult = {
  ok: true,
  message: 'Bucket verified — a round-trip write/read succeeded.',
};

/** Test/dev seam — control the next `testBucket` result. */
export function setMockTestOutcome(outcome: StorageMigrationTestResult): void {
  _testOutcome = outcome;
}

export const mockStorageMigrationService: StorageMigrationService = {
  testBucket(_input: StorageMigrationTestInput) {
    void _input;
    return delay({ ..._testOutcome });
  },
  startMigration(input: StorageMigrationStartInput) {
    const now = new Date().toISOString();
    const job: Job = {
      id: `job-${Math.random().toString(36).slice(2, 8)}`,
      tenantId: 't-1',
      type: 'storage_migration',
      status: 'pending',
      actorUserId: 'u-1',
      payload: { toConnectionId: 'conn-b', toBucket: input.config.bucket ?? input.name },
      result: null,
      progressTotal: 0,
      progressDone: 0,
      progressFailed: 0,
      error: null,
      createdAt: now,
      startedAt: null,
      finishedAt: null,
    };
    return delay(job);
  },
};
