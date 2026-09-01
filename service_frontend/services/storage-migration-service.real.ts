/** Real storage-migration service - FastAPI via the shared api-client. */
import { apiFetch } from '@/lib/api-client';
import type {
  Job,
  StorageMigrationStartInput,
  StorageMigrationTestInput,
  StorageMigrationTestResult,
} from '@/types/jobs';
import type { StorageMigrationService } from './storage-migration-service';

export const realStorageMigrationService: StorageMigrationService = {
  testBucket(input: StorageMigrationTestInput) {
    return apiFetch<StorageMigrationTestResult>('/storage/migrations/test', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  startMigration(input: StorageMigrationStartInput) {
    return apiFetch<Job>('/storage/migrations', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
};
