/**
 * Centralized background-jobs types (sprint-4/10) - the generic `background_jobs`
 * contract the Jobs drawer + `/jobs` list/detail speak. Storage migration is the
 * first `type`; the shapes stay type-agnostic so future job types ride them.
 *
 * Wire = camelCase, Z-suffixed datetimes (backend `JobOut`, `app/schemas/job.py`).
 */

/** Lifecycle states shared by every job type. */
export type JobStatus =
  | 'pending'
  | 'running'
  | 'needs_review'
  | 'done'
  | 'failed'
  | 'aborted';

/** Known job types (extensible - the drawer/list render any `type` string). */
export type JobType = 'storage_migration' | string;

/** One failed key in a storage-migration `result` (per-blob copy failure). */
export interface JobFailure {
  key: string;
  reason: string;
}

/** One milestone log line (backend `JobService.log`). */
export interface JobLogEntry {
  ts: string; // ISO Z
  level: string; // info | warning | error
  message: string;
}

/** A storage-migration `result_json` payload (other types carry their own). */
export interface StorageMigrationResult {
  copied: number;
  failed: number;
  orphaned: number;
  failures: JobFailure[];
}

/** A generic background job row. `payload`/`result` are type-specific bags. */
export interface Job {
  id: string;
  tenantId: string;
  type: JobType;
  status: JobStatus;
  actorUserId: string | null;
  payload: Record<string, unknown> | null;
  result: (StorageMigrationResult & Record<string, unknown>) | Record<string, unknown> | null;
  logs: JobLogEntry[] | null;
  progressTotal: number;
  progressDone: number;
  progressFailed: number;
  error: string | null;
  createdAt: string; // ISO Z
  startedAt: string | null;
  finishedAt: string | null;
}

/** `GET /jobs` response - camelCase, matches backend `JobListResponse`. */
export interface JobListResult {
  items: Job[];
  total: number;
}

/** Filters for `GET /jobs`. */
export interface JobListQuery {
  type?: JobType;
  status?: JobStatus;
  page?: number; // 0-based
  pageSize?: number;
}

/** Start a storage migration onto a new bucket B (`POST /storage/migrations`). */
export interface StorageMigrationStartInput {
  provider: string;
  name: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
}

/** Non-destructive new-bucket probe input (`POST /storage/migrations/test`). */
export interface StorageMigrationTestInput {
  provider: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
}

/** Result of the wizard's Test step. */
export interface StorageMigrationTestResult {
  ok: boolean;
  message: string;
}

/** Statuses that mean a job is still working (drives the drawer badge + poll). */
export const JOB_IN_FLIGHT: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'pending',
  'running',
]);

/** Statuses that need explicit user action (Complete / Retry). */
export const JOB_ATTENTION: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'needs_review',
  'failed',
]);
