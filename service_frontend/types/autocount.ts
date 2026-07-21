/**
 * AutoCount ESB types (sprint-4/13, slice 1) — the wire contract of the
 * `autocount` module's routers (`modules/autocount/schemas.py`).
 *
 * Wire = camelCase, Z-suffixed datetimes (every backend schema inherits
 * `ApiModel`). Nothing here carries a credential: a company's identity is the
 * DISCOVERED `databaseName`/`companyName`, and the connection's AppId/password
 * never leave the backend (AC-13-01/AC-13-42).
 */

// ── companies ────────────────────────────────────────────────────────────────

/** Sync mode of one entity on one company. */
export type AutocountSyncMode = 'AUTO' | 'SCHEDULED_REVIEW' | 'MANUAL';

/**
 * Per-entity sync configuration seeded when a company is registered, PLUS the
 * entity's live delta state.
 *
 * The watermark half is what makes a zero-record sync explicable: without
 * `lastSuccessAt`/`watermarkAt` on the surface, "0 records" is
 * indistinguishable from "broken", and `consecutiveFailures`/`lastError` were
 * recorded by every run and displayed nowhere.
 */
export interface AutocountEntityConfig {
  id: string;
  entityType: string;
  syncMode: AutocountSyncMode | string;
  sourceImpl: string;
  recordCap: number;
  /**
   * How far back the FIRST sync reaches when no watermark exists yet
   * (default 30). Anything older is invisible until the supervised full initial
   * load (D20, slice 3) — so this is shown, and editable, rather than hidden.
   */
  initialLookbackDays: number;
  enabled: boolean;
  /** Last run that completed cleanly. Null until the entity has ever synced. */
  lastSuccessAt: string | null; // ISO Z
  /** Last run attempted, successful or not. */
  lastAttemptAt: string | null; // ISO Z
  /** The high-water mark: "we hold everything modified up to here". */
  watermarkAt: string | null; // ISO Z
  /** Consecutive failed runs — the stale-sync signal (AC-13-19). */
  consecutiveFailures: number;
  lastError: string | null;
}

/** `PATCH /autocount/companies/{id}/entities/{entityType}` — narrow by design. */
export interface AutocountEntityConfigUpdate {
  initialLookbackDays?: number;
}

/**
 * One AutoCount company database. `databaseName`/`companyName` are DISCOVERED
 * from the login response and read-only — the vendor API resolves the company
 * from the AppId header, so an operator-entered value would be silently
 * overridden (AC-13-01).
 */
export interface AutocountCompany {
  id: string;
  connectionId: string;
  databaseName: string;
  companyName: string;
  /** Operator's display label (defaults to the discovered company name). */
  name: string;
  isActive: boolean;
  createdAt: string | null; // ISO Z
}

/** `GET /autocount/companies/{id}` — the company plus its entity configs. */
export interface AutocountCompanyDetail {
  company: AutocountCompany;
  entities: AutocountEntityConfig[];
}

/** `POST /autocount/companies` — the operator supplies ONLY a connection. */
export interface AutocountCompanyCreateInput {
  connectionId: string;
  /** Optional label; blank falls back to the discovered company name. */
  name?: string;
}

// ── sync ─────────────────────────────────────────────────────────────────────

/** Lifecycle of the `background_jobs` row behind a sync (core `JobStatus`). */
export type AutocountJobStatus =
  | 'pending'
  | 'running'
  | 'needs_review'
  | 'done'
  | 'failed'
  | 'aborted';

/** The background job a "Sync now" creates. */
export interface AutocountSyncJob {
  id: string;
  status: AutocountJobStatus | string;
  progressTotal: number;
  progressDone: number;
  progressFailed: number;
  result: Record<string, unknown> | null;
  error: string | null;
  createdAt: string | null; // ISO Z
}

/**
 * The `result` a finished `autocount_sync` job carries (`sync.py`'s summary).
 * Parsed rather than read blind so the UI can state the outcome — a run that
 * fetched nothing is a SUCCESSFUL no-op, not silence and not a failure.
 */
export interface AutocountSyncSummary {
  entityType: string | null;
  fetched: number;
  staged: number;
  failed: number;
  watermarkAdvancedTo: string | null;
  awaitingApproval: boolean;
}

function asCount(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** Read a job's `result` bag into the typed summary. Null when absent (a job
 * still pending under a real worker has no result yet). */
export function parseSyncSummary(
  result: Record<string, unknown> | null | undefined,
): AutocountSyncSummary | null {
  if (!result) return null;
  const advanced = result.watermarkAdvancedTo;
  return {
    entityType: typeof result.entityType === 'string' ? result.entityType : null,
    fetched: asCount(result.fetched),
    staged: asCount(result.staged),
    failed: asCount(result.failed),
    watermarkAdvancedTo: typeof advanced === 'string' ? advanced : null,
    awaitingApproval: result.awaitingApproval === true,
  };
}

/** Terminal state of one sync run. */
export type AutocountRunOutcome = 'SUCCESS' | 'FAILED' | 'ABORTED';

/** One executed sync run — the visible run state on a company. */
export interface AutocountSyncRun {
  id: string;
  entityType: string;
  jobId: string;
  windowFrom: string | null; // ISO Z
  windowTo: string | null; // ISO Z
  fetchedCount: number;
  stagedCount: number;
  failedCount: number;
  pushedCount: number;
  outcome: AutocountRunOutcome | string | null;
  error: string | null;
  /** True when the record cap was hit — a truncated sync must never read as a
   * complete one (AC-13-46). */
  truncated: boolean;
  watermarkAdvancedTo: string | null; // ISO Z
  startedAt: string | null; // ISO Z
  finishedAt: string | null; // ISO Z
}

/** Disposition of one staged record. */
export type AutocountStagedStatus = 'STAGED' | 'FAILED' | 'PUSHED' | 'DISCARDED';

/** One per-field mapping error on a staged record. */
export interface AutocountStagedError {
  field?: string;
  line?: number | string;
  message?: string;
  [key: string]: unknown;
}

/**
 * A record awaiting approval. `diff` holds CHANGED FIELDS ONLY — the backend's
 * `compute_diff` omits unchanged fields entirely, and deliberately ignores
 * `last_modified` (it moves on every fetch by definition). A first-seen record
 * carries the sentinel `{ __new__: true }` instead of per-field entries.
 */
export interface AutocountStagedRecord {
  id: string;
  entityType: string;
  sourceRef: string;
  docNo: string | null;
  status: AutocountStagedStatus | string;
  diff: Record<string, unknown> | null;
  canonical: Record<string, unknown> | null;
  errors: AutocountStagedError[] | null;
  error: string | null;
  sourceLastModified: string | null; // ISO Z
}

/** `GET /autocount/jobs/{id}/staged` — the review surface's payload. */
export interface AutocountStagedList {
  job: AutocountSyncJob;
  data: AutocountStagedRecord[];
  total: number;
}

/** `POST /autocount/jobs/{id}/{approve,discard}` — idempotent (AC-13-13). */
export interface AutocountApprovalResult {
  jobId: string;
  result: Record<string, unknown>;
}

// ── diff view model (AC-13-12) ───────────────────────────────────────────────

/** One changed field, before → after. */
export interface AutocountFieldChange {
  field: string;
  from: unknown;
  to: unknown;
}

/** The parsed, renderable form of a staged record's `diff`. */
export interface AutocountRecordDiff {
  /** First time we have seen this record — there is no "before". */
  isNew: boolean;
  /** Changed fields ONLY. Empty for a new record and for a no-change record. */
  changes: AutocountFieldChange[];
}
