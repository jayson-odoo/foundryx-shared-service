/**
 * AutoCount ESB types (sprint-4/13, slice 1) - the wire contract of the
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
   * load (D20, slice 3) - so this is shown, and editable, rather than hidden.
   */
  initialLookbackDays: number;
  enabled: boolean;
  /** Last run that completed cleanly. Null until the entity has ever synced. */
  lastSuccessAt: string | null; // ISO Z
  /** Last run attempted, successful or not. */
  lastAttemptAt: string | null; // ISO Z
  /** The high-water mark: "we hold everything modified up to here". */
  watermarkAt: string | null; // ISO Z
  /** Consecutive failed runs - the stale-sync signal (AC-13-19). */
  consecutiveFailures: number;
  lastError: string | null;
}

/** `PATCH /autocount/companies/{id}/entities/{entityType}` - narrow by design. */
export interface AutocountEntityConfigUpdate {
  initialLookbackDays?: number;
}

/**
 * One AutoCount company database. `databaseName`/`companyName` are DISCOVERED
 * from the login response and read-only - the vendor API resolves the company
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
  /**
   * The consumer push target (hop 2). `logging` = the no-op default (nothing
   * leaves the ESB); `sorento` + `sinkConnectionId` = a real Sorento push.
   */
  sinkImpl: AutocountSinkImpl | string;
  /** Core `connections.id` of the `consumer` connection; null for `logging`. */
  sinkConnectionId: string | null;
  createdAt: string | null; // ISO Z
}

/** `GET /autocount/companies/{id}` - the company plus its entity configs. */
export interface AutocountCompanyDetail {
  company: AutocountCompany;
  entities: AutocountEntityConfig[];
}

/** Which consumer sink a company delivers to (`CompanyItem.sinkImpl`). */
export type AutocountSinkImpl = 'logging' | 'sorento';

/**
 * `PATCH /autocount/companies/{id}/sink-target`. `logging` = the no-op default
 * (nothing leaves the ESB); `sorento` requires `sinkConnectionId` naming a
 * Sorento `consumer` connection for this tenant.
 */
export interface AutocountSinkTargetInput {
  sinkImpl: AutocountSinkImpl;
  sinkConnectionId?: string | null;
}

/** `POST /autocount/companies` - the operator supplies ONLY a connection. */
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
 * Parsed rather than read blind so the UI can state the outcome - a run that
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

/** One executed sync run - the visible run state on a company. */
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
  /** True when the record cap was hit - a truncated sync must never read as a
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
 * A record awaiting approval. `diff` holds CHANGED FIELDS ONLY - the backend's
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
  /**
   * Whether any MAPPED field actually changed (or the record is a first-seen /
   * failed one the operator must see). A delta re-fetch whose only movement was
   * AutoCount's `LastModified` has `hasChanges: false` and is collapsed into a
   * count rather than shown as a full card (AC-15-11). Backend-computed off the
   * same `compute_diff` that fills `diff`.
   */
  hasChanges: boolean;
  sourceLastModified: string | null; // ISO Z
}

/**
 * `GET /autocount/jobs/{id}/staged` query. The staged list is server-paginated
 * (AC-15-10) - an all-rows fetch is never issued. `changed` narrows the page to
 * records the operator must act on (`true`) or the collapsed no-change set
 * (`false`); omitted = the whole batch.
 */
export interface AutocountStagedQuery {
  page?: number; // 0-based
  pageSize?: number;
  /** Matches source ref / doc no / name. */
  search?: string;
  /** true = changed + failed rows; false = no-field-change rows; omit = all. */
  changed?: boolean;
  /** One staged status (`STAGED`/`FAILED`/…) - the list's Filters control. */
  status?: AutocountStagedStatus | string;
}

/** `GET /autocount/jobs/{id}/staged` - the review surface's payload. */
export interface AutocountStagedList {
  job: AutocountSyncJob;
  data: AutocountStagedRecord[];
  /** Rows matching THIS query (drives pagination). */
  total: number;
  /**
   * Count of no-field-change records in the whole batch (constant across
   * pages) - lets the FE render the collapsed "N with no field changes" line
   * without fetching them (AC-15-11).
   */
  noChangeCount: number;
}

/** `POST /autocount/jobs/{id}/{approve,discard}` - idempotent (AC-13-13). */
export interface AutocountApprovalResult {
  jobId: string;
  result: Record<string, unknown>;
}

// ── review jobs list (plan 15 §2, AC-15-02) ──────────────────────────────────

/**
 * One sync batch (job) row on the Review list (`GET /autocount/jobs`). Denormal-
 * ised with the owning company + entity so the list is scannable without a
 * per-row company fetch. Newest first; tenant-scoped server-side.
 */
export interface AutocountSyncJobBatch {
  jobId: string;
  companyId: string;
  companyName: string;
  databaseName: string;
  entityType: string;
  status: AutocountJobStatus | string;
  progressTotal: number;
  progressDone: number;
  progressFailed: number;
  createdAt: string | null; // ISO Z
  startedAt: string | null; // ISO Z
  finishedAt: string | null; // ISO Z
  updatedAt: string | null; // ISO Z
}

/**
 * `GET /autocount/jobs` query. `status` is the review segment
 * (`needs_review|done|all`) - server-filtered, never an unbounded fetch.
 */
export interface AutocountJobListQuery {
  page?: number; // 0-based
  pageSize?: number;
  status?: 'needs_review' | 'done' | 'all' | string;
  entityType?: string;
}

// ── field-mapping editor (plan 15 §2, AC-15-40..44) ──────────────────────────

/**
 * One mapping row as the editor sees it: an AutoCount source path → (transform)
 * → Sorento field. `sorentoField` is null for a PROVENANCE/identity row (e.g.
 * `last_modified`) that is stored canonically but never delivered to Sorento -
 * shown non-deliverable, never offered for edit (AC-15-40).
 */
export interface AutocountMappingRow {
  sourcePath: string;
  transform: string;
  /**
   * The row's safe transform formula (slice 16). NULL ⇒ the named `transform`
   * runs (today's behavior, exact); a non-empty formula is authoritative and
   * evaluated by the mirrored engine (`lib/autocount-formula.ts`).
   */
  formula: string | null;
  sorentoField: string | null;
  canonicalField: string;
  scope: string;
  isRequired: boolean;
  isEnabled: boolean;
}

/** One accepted Sorento target for the picker (AC-15-42) - the offered set. */
export interface AutocountSorentoField {
  field: string;
  required: boolean;
}

/** `GET .../mapping` - current rows + the source/target catalogs the pickers need. */
export interface AutocountMappingView {
  entityType: string;
  rows: AutocountMappingRow[];
  /** The ONLY Sorento targets the picker offers (foolproof, AC-15-42). */
  sorentoFields: AutocountSorentoField[];
  /** Known AutoCount source paths (discoverability; a free dotted path is allowed). */
  acFields: string[];
}

/** One deliverable row on write. `sorentoField` must be an accepted target. */
export interface AutocountMappingWriteRow {
  sourcePath: string;
  transform: string;
  sorentoField: string;
  /**
   * Optional safe transform formula (slice 16). NULL/blank ⇒ the named
   * `transform` runs; a non-empty formula is validated server-side (parse
   * 422, AC-16-03) and becomes authoritative.
   */
  formula?: string | null;
}

/** `PUT .../mapping` body - replaces the entity's deliverable rows transactionally. */
export interface AutocountMappingUpdate {
  rows: AutocountMappingWriteRow[];
}

// ── formula catalog + simulators (plan 16 §3, AC-16-13/21/30) ─────────────────

/**
 * `POST .../mapping/test-formula` result (AC-16-21) - the server-authoritative
 * single-formula eval, the parity check behind the builder's live client
 * preview. Same shape as `lib/autocount-formula.ts testFormula`.
 */
export interface AutocountFormulaTestResult {
  ok: boolean;
  output: unknown;
  error: string | null;
}

/** One field's simulated outcome in the whole-mapping preview - value or error. */
export interface AutocountSimulateFieldResult {
  scope: string;
  sourcePath: string;
  canonicalField: string;
  present: boolean;
  ok: boolean;
  value: unknown;
  error: string | null;
}

/**
 * `POST .../mapping/simulate` result (AC-16-30/31) - the REAL MappingEngine run
 * over a mock AutoCount record. `record` is the projected Sorento payload (every
 * mapped field), or null when the record would be REJECTED (all-or-nothing per
 * document). Writes NOTHING - pure transform preview.
 */
export interface AutocountSimulateResult {
  ok: boolean;
  sourceRef: string;
  docNo: string | null;
  record: Record<string, unknown> | null;
  headerFields: AutocountSimulateFieldResult[];
  lineFields: AutocountSimulateFieldResult[][];
  errors: Array<Record<string, unknown>>;
}

// ── dry-run preview (hop 2, AC-14-20/21/22/26) ───────────────────────────────

/**
 * The consumer's dry-run counts, mirrored from Sorento (AC-14-26). `total` is
 * stated alongside so a partial preview is never mistaken for a clean success.
 * Extra keys the vendor may add are tolerated (the summary is a plain int bag
 * server-side).
 */
export interface AutocountPreviewSummary {
  total: number;
  created: number;
  updated: number;
  failed: number;
  retryable: number;
  [key: string]: number;
}

/** One field's before → after in a prediction. `incoming: null` = a BLANKING. */
export interface AutocountPreviewFieldDiff {
  current: unknown;
  incoming: unknown;
}

/**
 * One record's dry-run verdict (AC-14-20/22). Authoritative - it is Sorento's
 * own `?dry_run=true` resolution rolled back, never a local reconstruction.
 * `changesLiveData` marks the rows that would OVERWRITE live values.
 */
export interface AutocountPrediction {
  sourceRef: string;
  /** `created` | `updated` (adoption reports `updated`) | `failed`. */
  outcome: string;
  entityId: string | null;
  changesLiveData: boolean;
  /** `column → {current, incoming}`. Empty for a create. */
  diff: Record<string, AutocountPreviewFieldDiff>;
  errors: Record<string, unknown>;
}

/** A previewable dry-run result (a company pushing to the Sorento sink). */
export interface AutocountPreviewOk {
  previewable: true;
  sink: string;
  summary: AutocountPreviewSummary;
  predictions: AutocountPrediction[];
}

/** No consumer to ask (logging sink) - a clear "nothing to preview", not an error. */
export interface AutocountPreviewUnavailable {
  previewable: false;
  sink: string;
  reason: string;
}

/** Either shape the `preview` block carries (the service owns which). */
export type AutocountPreview = AutocountPreviewOk | AutocountPreviewUnavailable;

/** `POST /autocount/jobs/{id}/preview`. */
export interface AutocountPreviewResult {
  jobId: string;
  preview: AutocountPreview;
}

/**
 * Split a previewable result's predictions into the rows an operator must see
 * (they overwrite live data) and the rest (creates / no-change updates), so the
 * overwrites are never buried under a wall of creates (AC-14-20).
 */
export interface AutocountPreviewPartition {
  overwrites: AutocountPrediction[];
  created: AutocountPrediction[];
  otherUpdates: AutocountPrediction[];
  failed: AutocountPrediction[];
}

export function partitionPredictions(
  predictions: AutocountPrediction[],
): AutocountPreviewPartition {
  const overwrites: AutocountPrediction[] = [];
  const created: AutocountPrediction[] = [];
  const otherUpdates: AutocountPrediction[] = [];
  const failed: AutocountPrediction[] = [];
  for (const p of predictions) {
    if (p.outcome === 'failed') failed.push(p);
    else if (p.changesLiveData) overwrites.push(p);
    else if (p.outcome === 'created') created.push(p);
    else otherUpdates.push(p);
  }
  return { overwrites, created, otherUpdates, failed };
}

/**
 * True when this field's incoming value BLANKS an existing one - the
 * destructive case (AC-14-22): a live value replaced by nothing.
 */
export function isBlanking(change: AutocountPreviewFieldDiff): boolean {
  const emptyIncoming =
    change.incoming === null || change.incoming === undefined || change.incoming === '';
  const hadValue =
    change.current !== null && change.current !== undefined && change.current !== '';
  return emptyIncoming && hadValue;
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
  /** First time we have seen this record - there is no "before". */
  isNew: boolean;
  /** Changed fields ONLY. Empty for a new record and for a no-change record. */
  changes: AutocountFieldChange[];
}
