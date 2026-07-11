/**
 * Storage-migration service (sprint-4/10) — starts a migration onto a new
 * bucket B and probes a candidate bucket (the wizard's Test step). The
 * interface IS the backend contract (`POST /storage/migrations`,
 * `POST /storage/migrations/test`).
 *
 * `testBucket` reuses the SAME `run_probe` (head_bucket + round-trip) the
 * connect wizard's Test + the migration `start` run — non-destructive so Start
 * can be gated on it (foolproof-UI). Frontend-first: iterate on `.mock`, the
 * shipped boundary below is `.real`.
 */
import type {
  Job,
  StorageMigrationStartInput,
  StorageMigrationTestInput,
  StorageMigrationTestResult,
} from '@/types/jobs';
import { realStorageMigrationService } from './storage-migration-service.real';

export interface StorageMigrationService {
  /** Non-destructive probe of the candidate new bucket (Test step). */
  testBucket(input: StorageMigrationTestInput): Promise<StorageMigrationTestResult>;
  /** Atomically create B + flip write-target + enqueue the drain job. */
  startMigration(input: StorageMigrationStartInput): Promise<Job>;
}

export const storageMigrationService: StorageMigrationService =
  realStorageMigrationService;
