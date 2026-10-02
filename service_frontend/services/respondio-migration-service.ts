/**
 * respond.io migration service (plan 33, roadmap A6). The interface IS the
 * real backend contract §5.2 as built across S1-S5: preflight, uploads
 * (CSV mode), jobs list/create/get/cancel, the authed failures CSV download.
 * Connections and target workspaces reuse the EXISTING generic catalogs
 * (`integration-service`, `workspace-service`) filtered to this feature's
 * shape - this module never re-lists them from scratch.
 *
 * S0-S5 built + tuned every state against `.mock`; S6 (AC-MIG-56) flips the
 * shipped binding below to `.real`. The mock file survives as the frontend
 * test fixture (`.mock.test.ts`) - it is no longer reachable from any page.
 */
import type {
  CreateMigrationJobInput,
  MigrationJob,
  MigrationPreflight,
  MigrationUploadResult,
} from '@/types/respondio-migration';
import type { ListQuery, ListResult } from '@/types/resource';
import { realRespondioMigrationService } from './respondio-migration-service.real';

export interface RespondioMigrationService {
  /** `GET /omnichannel/migration/preflight?connectionId=&workspaceId=`
   *  (AC-MIG-14). Zero writes. */
  preflight(connectionId: string, workspaceId: string): Promise<MigrationPreflight>;
  /** `POST /omnichannel/migration/uploads` (multipart, S5 AC-MIG-46/47) -
   *  `kind=contacts` for the CSV-mode contacts file, `kind=snippets` for the
   *  quick-replies CSV (either mode). Returns an OPAQUE receipt id (review
   *  round 1, finding B2 - never a raw storage key) the job payload then
   *  references, plus the sniffed row count and headers. */
  uploadCsv(kind: 'contacts' | 'snippets', file: File): Promise<MigrationUploadResult>;
  /** `GET /omnichannel/migration/jobs` - tenant-scoped job history. */
  listJobs(query: ListQuery): Promise<ListResult<MigrationJob>>;
  /** `GET /omnichannel/migration/jobs/{jobId}` - report inline. */
  getJob(jobId: string): Promise<MigrationJob>;
  /** `POST /omnichannel/migration/jobs`. 409 `dry_run_required` |
   *  `migration_in_progress`; 422 `{fieldErrors}`. */
  createJob(input: CreateMigrationJobInput): Promise<MigrationJob>;
  /** `POST /omnichannel/migration/jobs/{jobId}/cancel` - a DEDICATED route,
   *  never the generic `/jobs/{id}/abort` (that route is hard-scoped to
   *  `StorageMigrationService`; the S2 handoff flagged this explicitly for
   *  S6 to wire correctly). 409 when the job is already terminal. */
  cancelJob(jobId: string): Promise<MigrationJob>;
  /** `GET /omnichannel/migration/jobs/{jobId}/failures.csv` - authed
   *  streaming download (D-A6-23), never a signed capability URL. Returns
   *  the CSV text; the caller triggers the client-side Blob download (the
   *  system-wide export convention, `resource-list.tsx` `downloadCsv`). */
  downloadFailuresCsv(jobId: string): Promise<string>;
}

// S6 (AC-MIG-56): the shipped boundary is the real api-client impl.
export const respondioMigrationService: RespondioMigrationService = realRespondioMigrationService;
