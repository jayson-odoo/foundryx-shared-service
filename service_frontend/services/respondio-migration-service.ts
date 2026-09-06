/**
 * respond.io migration service (plan 33 S0, roadmap A6). S0 MOCK - swap to
 * real in S6 (one line at the bottom). The interface IS the backend
 * contract §5.2: preflight, jobs list/create/get, the authed failures CSV
 * download. Connections and target workspaces reuse the EXISTING generic
 * catalogs (`integration-service`, `workspace-service`) filtered to this
 * feature's shape - this module never re-lists them from scratch.
 */
import type {
  CreateMigrationJobInput,
  MigrationJob,
  MigrationPreflight,
} from '@/types/respondio-migration';
import type { ListQuery, ListResult } from '@/types/resource';
import { mockRespondioMigrationService } from './respondio-migration-service.mock';

export interface RespondioMigrationService {
  /** `GET /omnichannel/migration/preflight?connectionId=&workspaceId=`
   *  (AC-MIG-14). Zero writes. */
  preflight(connectionId: string, workspaceId: string): Promise<MigrationPreflight>;
  /** `GET /omnichannel/migration/jobs` - tenant-scoped job history. */
  listJobs(query: ListQuery): Promise<ListResult<MigrationJob>>;
  /** `GET /omnichannel/migration/jobs/{jobId}` - report inline. */
  getJob(jobId: string): Promise<MigrationJob>;
  /** `POST /omnichannel/migration/jobs`. 409 `dry_run_required` |
   *  `migration_in_progress`; 422 `{fieldErrors}`. */
  createJob(input: CreateMigrationJobInput): Promise<MigrationJob>;
  /** `GET /omnichannel/migration/jobs/{jobId}/failures.csv` - authed
   *  streaming download (D-A6-23), never a signed capability URL. Returns
   *  the CSV text; the caller triggers the client-side Blob download (the
   *  system-wide export convention, `resource-list.tsx` `downloadCsv`). */
  downloadFailuresCsv(jobId: string): Promise<string>;
}

// PHASE 1 MOCK (S0 MOCK - swap to real in S6): frontend-first against the
// mock; the boundary flips to `realRespondioMigrationService` in ONE line.
export const respondioMigrationService: RespondioMigrationService = mockRespondioMigrationService;
