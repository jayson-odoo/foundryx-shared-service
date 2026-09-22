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
 * Where an entity's records are READ from (`ac_entity_config.source_impl`,
 * plan 22 §2): the vendor HTTP API (the plan-13 path, untouched) or a direct
 * read-only SQL extraction task. Switching changes how every sync runs.
 */
export type AutocountSourceImpl = 'autocount_read' | 'sql_db' | 'autocount_http';

/**
 * How a company is connected (plan sprint-5/01, AC-01-07; `'http'` added
 * sprint-5/08 D1/D8): DERIVED server-side from its ONE connection's provider -
 * `autocount` (auth `basic`) → `'api'`, `autocount` (auth `none`, the open
 * REST wrapper) → `'http'`, `sql_database` → `'db'`. Never stored, never
 * client-supplied. A DB or open (`http`) company has no vendor login: a `db`
 * company reads through `sql_db` tasks locked to the company connection; an
 * `http` company's tasks read `autocount_http` locked to the SAME open
 * connection (there is no separate onboarding step - the company IS the
 * connection).
 */
export type AutocountSourceKind = 'api' | 'db' | 'http';

/** Auth mode of an `autocount` connection (sprint-5/08, D1). `basic` = the
 * vendor login (AppId + user + password, today's grammar, GRN/supplier/
 * customer only); `none` = the open REST wrapper (base URL only, every
 * `AC_HTTP_ENTITY_TYPES` entity). Absent/legacy connection rows behave as
 * `basic` (`auth_mode(config)` on the backend). */
export type AutocountConnectionAuth = 'basic' | 'none';

/**
 * One document entity's prerequisite-master status (AC-01-11). A sales order
 * needs `customer` + `product`, a purchase order `supplier` + `product` - the
 * refs Sorento cannot NULL. While any is missing/inactive the document's rows
 * stay `retryable` (never lost), so the Entities tab warns instead of blocking.
 */
export interface AutocountDocumentPrerequisite {
  entityType: string;
  /** Prerequisite masters with no entity config row at all. */
  missing: string[];
  /** Masters configured but not active (`etl_status != 'active'` or disabled). */
  inactive: string[];
}

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
  sourceImpl: AutocountSourceImpl | string;
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
  /**
   * The DB-task lifecycle (`draft|active|paused`, plan 22 §2.4, AC-22-23) -
   * carried on the LIST (not just the task editor) so the Review & Activate
   * tab can warn a `product` task's activation of a missing category/UOM
   * prerequisite without a second fetch.
   */
  etlStatus: AutocountEtlStatus;
  /**
   * `push` (today's behaviour) or `pull` (sprint-5/10, D1/D2) - the task
   * never auto-pushes and never runs on the sweep; a consumer/operator
   * request builds a snapshot on demand instead. Every task before this
   * plan reads `push`. Carried on the LIST so the Delivery column
   * (AC-10-17) needs no per-row fetch. Optional/absent reads as `push`
   * (back-compat with a fixture built before this field existed, same
   * convention as `AutocountEtlTask.sourceImpl`).
   */
  deliveryMode?: AutocountDeliveryMode;
}

/**
 * `PATCH /autocount/companies/{id}/entities/{entityType}` - narrow by design.
 * `sourceImpl` (plan 22 S2) switches the entity between the API path and the
 * DB task; the backend keeps the task's `source_config` either way (switching
 * back to the API never discards a configured query) and an ACTIVE task
 * switched to the API path is paused first (never left auto-pushing).
 */
export interface AutocountEntityConfigUpdate {
  initialLookbackDays?: number;
  sourceImpl?: AutocountSourceImpl;
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
  /**
   * The Sorento company this AutoCount company delivers INTO
   * (`ac_company.sorento_company_code`, plan 22 Appendix A6). Sent as the
   * top-level `companyCode` on every ingest/read/deletion call; REQUIRED when
   * `sinkImpl === 'sorento'` - blank = every push fails with an anchor 422.
   */
  sorentoCompanyCode: string | null;
  createdAt: string | null; // ISO Z
  /** Derived from the connection's provider (AC-01-07); a deleted connection reports `'api'`. */
  sourceKind: AutocountSourceKind;
  /**
   * Prerequisite-master status per configured document entity (AC-01-11).
   * Populated on `GET /autocount/companies/{id}`; the LIST returns `[]`.
   */
  documentPrerequisites: AutocountDocumentPrerequisite[];
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
  /** Required with `sorento` (trimmed, matched case-insensitively by Sorento). */
  sorentoCompanyCode?: string | null;
}

/**
 * `POST /autocount/companies` - the operator supplies ONLY a connection. The
 * server branches on its provider (AC-01-01): an `autocount` connection signs
 * in to discover the company; a `sql_database` connection derives the identity
 * from `config.database` (verified by a live probe, AC-01-02).
 */
export interface AutocountCompanyCreateInput {
  connectionId: string;
  /** Optional label; blank falls back to the discovered company name. */
  name?: string;
  /**
   * REQUIRED when `connectionId` names an open (no-auth) `autocount`
   * connection (sprint-5/08, AC-08-06/07/D4) - the operator-typed reference
   * prefix every pushed ref carries (`{prefix}:{key}`), stored as
   * `ac_company.database_name`, immutable once created. Ignored (422 "not
   * applicable") for a vendor or SQL connection.
   */
  refPrefix?: string;
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

/** Terminal state of one sync run. `SKIPPED` = an overlap-guarded tick that
 * never ran (AC-22-14) - recorded, never queued behind. */
export type AutocountRunOutcome = 'SUCCESS' | 'FAILED' | 'ABORTED' | 'SKIPPED';

/** How a run was started (`ac_sync_run.mode`, plan 22 §2.7). */
export type AutocountRunMode = 'manual' | 'incremental' | 'reconcile' | 'skipped';

/** One executed sync run - the visible run state on a company. */
export interface AutocountSyncRun {
  id: string;
  entityType: string;
  /** Null for a skipped tick (nothing was enqueued). */
  jobId: string | null;
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
  // ── plan 22 §2.7 cost columns (AC-22-17) - `manual` for every API-path run ──
  mode: AutocountRunMode | string;
  /** Source rows read (the volume × frequency signal). */
  rowsScanned: number;
  addedCount: number;
  updatedCount: number;
  /** Delete intents pushed (reconcile only). */
  deletedCount: number;
  durationMs: number | null;
  /** Why a `skipped` tick did not run (e.g. the previous run was still going). */
  skipReason: string | null;
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
  /**
   * Document entities only (sprint-5/02, AC-02-02) - the accepted LINE targets
   * (`source_ref`/`product_ref`/`qty_ordered` required, etc). Empty for a
   * master/GRN entity - the Mapping tab renders a single section then.
   */
  lineSorentoFields: AutocountSorentoField[];
  /** Document entities only - the task's persisted `line_result_columns`
   * (empty until the line query has been saved with a successful preview). */
  lineAcFields: string[];
  /**
   * sprint-5/12 (AC-12-21, D5) - whether this entity has a preset a "Reset
   * to preset" action could apply. Server-derived by the SAME rule the
   * reset itself uses (AC-12-11) - the UI never infers it from the entity
   * type, so an HTTP task and a DB task of the same entity can differ.
   * Optional/absent reads as `false` (back-compat with every fixture built
   * before this field existed - the same convention as `deliveryMode`
   * elsewhere in this file).
   */
  hasPreset?: boolean;
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
  /**
   * `'header'` (default when omitted) or `'line'` (sprint-5/02, AC-02-01) -
   * a document entity's line rows are a SEPARATE scope from its header rows
   * sharing the same `canonical_field` vocabulary is allowed (e.g. `currency`
   * on both). Master/GRN entities never send `'line'`.
   */
  scope?: 'header' | 'line';
  /**
   * B1 (final review round) - carries a backfill/preset-disabled row's
   * enabled state through the save so it round-trips unchanged rather than
   * silently defaulting to enabled server-side (which re-triggers the S1
   * preview-column gate for an off-preview fixed-field row).
   */
  isEnabled?: boolean;
}

/** `PUT .../mapping` body - replaces the entity's deliverable rows transactionally. */
export interface AutocountMappingUpdate {
  /** Header-scope rows (a master/GRN entity's whole mapping). */
  rows: AutocountMappingWriteRow[];
  /**
   * The wire signal a header-only save needs (security re-review should-fix,
   * sprint-5/02 review round) - a document entity's line rows are a
   * SEPARATE scope now: omit this field entirely to leave line rows
   * untouched, send `[]` to explicitly wipe them, send the current line
   * draft to replace it. `rows` alone can never express "no lineRows key"
   * vs "lineRows: []" once both arrive as an empty slice.
   */
  lineRows?: AutocountMappingWriteRow[];
}

// ── mapping preset reset (sprint-5/12, Group B - AC-12-10..24) ───────────────

/**
 * One preset row's dry-run diff against the entity's CURRENT header mapping
 * (`POST .../mapping/reset-preset {dryRun: true}`, AC-12-12). `change` is
 * `'added'` (no current row for this canonical field), `'changed'` (a
 * current row exists and its source/transform/formula/enabled differs) or
 * `'unchanged'`. `disabledReason` is present ONLY when `enabled` is false -
 * a fixed, uniform string (the row's source column is not returned by the
 * task's current preview/lookups - the SAME AC-02-16 rule a first-save seed
 * already follows, reused here).
 */
export interface AutocountMappingResetRow {
  canonicalField: string;
  sourcePath: string;
  transform: string;
  formula: string | null;
  enabled: boolean;
  isRequired: boolean;
  change: 'added' | 'changed' | 'unchanged';
  disabledReason?: string;
}

/** One CURRENT header row the preset would drop (AC-12-12) - shown under
 *  the dialog's "Removed" section, never silently discarded (R2's accepted
 *  trade: a whole-mapping replace, previewed first). */
export interface AutocountMappingResetRemovedRow {
  canonicalField: string;
  sourcePath: string;
  transform: string;
  formula: string | null;
}

/**
 * `POST .../mapping/reset-preset {dryRun: true}` result (AC-12-12) - the
 * exact diff a reset would apply, header scope only (D3: `source_config`/
 * lookups are untouched - a reset never re-arms the Test/Activate gate).
 * Writes nothing.
 */
export interface AutocountMappingResetPreview {
  label: string;
  rows: AutocountMappingResetRow[];
  removed: AutocountMappingResetRemovedRow[];
}

/** Narrows the `resetMappingToPreset` union - the dry-run shape carries
 *  `rows`/`removed`, the apply shape (`AutocountMappingView`) does not. */
export function isMappingResetPreview(
  result: AutocountMappingResetPreview | AutocountMappingView,
): result is AutocountMappingResetPreview {
  // `removed` is unique to the preview shape - both types carry `rows`.
  return 'removed' in result;
}

/** True when every row is unchanged and nothing would be removed - the
 *  dialog's "already matches the preset" gate (AC-12-22). */
export function isMappingResetPreviewEmpty(preview: AutocountMappingResetPreview): boolean {
  return preview.removed.length === 0 && preview.rows.every((r) => r.change === 'unchanged');
}

// ── mapping/query presets (sprint-5/02, AC-02-16/17) ─────────────────────────

/**
 * `GET /autocount/presets/{entityType}` (S3 backend) - the AutoCount SQL-pack
 * preset for one document entity, with the placeholder `{database}` already
 * substituted for the company's `databaseName`. "Use preset" on the Query tab
 * inserts the whole thing (header + line query, the picker defaults, and the
 * filter formula); the mapping rows it seeds ride the SAME task-save path as
 * any other first save of an empty mapping (AC-02-16) - this type carries only
 * what the Query tab writes directly.
 */
export interface AutocountMappingPreset {
  entityType: string;
  label: string;
  headerQuery: string;
  lineQuery: string | null;
  keyColumns: string[];
  watermarkColumn: string | null;
  docDateColumn: string | null;
  fromDate: string | null;
  filterFormula: string | null;
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
  /**
   * Document entities only (sprint-5/02, AC-02-08/22) - the header's computed
   * `status` (from the status formula run AFTER the lines + aggregates), or
   * null when the row isn't mapped / the record was rejected. Also present
   * inside `record.status` - carried separately so the dialog can render it
   * as a badge without re-parsing the payload.
   */
  status?: string | null;
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

// ── direct-DB ETL (plan 22, slice S1 - AC-22-01..07/11) ──────────────────────

/** Supported read-only SQL source dialects (grill post-decision). */
export type AutocountSqlDialect = 'mssql' | 'postgresql' | 'mysql';

/** One tenant SQL-database connection the task editor may point at
 * (`GET /autocount/sql/connections` - tenant + provider `sql_database` scoped,
 * never a bare connections fetch). */
export interface AutocountSqlConnection {
  id: string;
  name: string;
  dialect: AutocountSqlDialect | string;
  database: string;
}

/** One introspected column (name + the dialect's reported type). */
export interface AutocountSqlColumn {
  name: string;
  type: string;
}

/** One introspected table. Columns arrive with the schema payload (the
 * introspection is cached server-side per connection, AC-22-05). */
export interface AutocountSqlTable {
  name: string;
  columns: AutocountSqlColumn[];
}

/** One namespace within the database (e.g. `dbo`, `public`). */
export interface AutocountSqlSchemaNode {
  name: string;
  tables: AutocountSqlTable[];
}

/**
 * `GET /autocount/sql/connections/{id}/schema[?refresh=true]` - the cached
 * schemas → tables → columns tree (AC-22-05). `refresh=true` busts the
 * server-side cache; the tree is NEVER fetched per keystroke.
 */
export interface AutocountSqlSchema {
  connectionId: string;
  dialect: AutocountSqlDialect | string;
  database: string;
  schemas: AutocountSqlSchemaNode[];
  introspectedAt: string; // ISO Z
}

/** One result column of a preview run (name + reported type, AC-22-06). */
export interface AutocountSqlPreviewColumn {
  name: string;
  type: string;
}

/**
 * `POST /autocount/sql/preview` result. At most 100 rows (dialect-appropriate
 * wrapping server-side); `truncated` is true when the cap cut the result - the
 * UI must never present a capped preview as the whole set (AC-22-06).
 */
export interface AutocountSqlPreview {
  columns: AutocountSqlPreviewColumn[];
  rows: Array<Record<string, unknown>>;
  /** Rows returned (≤ 100). */
  rowCount: number;
  /** True when the 100-row cap cut the result. */
  truncated: boolean;
  durationMs: number;
}

/** Lifecycle of a DB extraction task (plan 22 §2.4 `etl_status`). */
export type AutocountEtlStatus = 'draft' | 'active' | 'paused';

/**
 * The `source_config` JSON of a `sql_db` task (plan 22 §2.4) - the Query tab
 * owns connection/query/columns/fromDate; the Schedule tab (S3) owns the
 * cadence fields, carried here so a draft save round-trips the whole document.
 */
export interface AutocountEtlSourceConfig {
  /** Core `connections.id` of a `sql_database` connection (tenant-validated
   * server-side on every use - polymorphic-stored-id rule). */
  connectionId: string | null;
  /** The extraction SELECT (single statement; server guard rejects anything
   * else with 422 before touching the source, AC-22-03). */
  query: string;
  /** Document entities (SO/PO) only: per-changed-header line query with a
   * `:doc_key` bound param. One task, two queries - never a separate lines task. */
  lineQuery: string | null;
  /** Result columns minting the source_ref (`{database}:{key1[|key2]}`). Must
   * exist in the preview result columns at save (AC-22-11). */
  keyColumns: string[];
  /** Orderable result column driving incremental fetches; null = hash-diff
   * incremental (interval floor 15 min). */
  watermarkColumn: string | null;
  /** "On change of which fields" - empty = all result columns minus keys. */
  comparedColumns: string[];
  /** Documents only (YYYY-MM-DD, default today). */
  fromDate: string | null;
  /** Documents only (plan 22 S5) - the header column the from-date floor
   * filters (the document's OWN date, e.g. DocDate - deliberately separate
   * from `watermarkColumn`/LastModified, which drives change detection). */
  docDateColumn: string | null;
  /**
   * Documents only (sprint-5/02, AC-02-11) - a per-task boolean formula over
   * HEADER columns (`AutocountFormulaBuilder`, never free text). A header
   * evaluating false is skipped before the line fetch - never staged, never a
   * delete candidate. Null = every header passes (the default for a
   * never-configured task). Decides the SO/SPO family split
   * (`not(startswith(upper(trim(DocNo)), "SPO-"))` / the SPO counterpart).
   */
  filterFormula: string | null;
  incrementalMinutes: number;
  reconcileMode: 'interval' | 'dailyAt';
  reconcileHours: number | null;
  /** "HH:MM" in the tenant timezone (`reconcileMode === 'dailyAt'`). */
  reconcileAt: string | null;
  // ── sprint-5/08 (D13) - present only when the task's Source is API/`autocount_http` ──
  //
  // PHASE 1 MOCK simplification (see the contract block atop
  // `autocount-service.ts`): rather than a discriminated `sourceConfig`
  // union, the open-API fields ride the SAME envelope as the SQL fields
  // above (mutually exclusive by which half is populated) so Mapping /
  // Schedule / Review & Activate / Runs keep reading ONE `AutocountEtlTask.
  // sourceConfig` shape unchanged (AC-08-19: "the existing components
  // untouched"). `AutocountHttpSourceConfig` below documents the field names
  // the UAC's wire contract actually uses (`keyFields` not `keyColumns`,
  // etc.) - the backend phase (S2/S3) is free to keep them as a nested JSON
  // as long as this FE envelope's mapping stays exact.
  /** Relative endpoint path (`/itembypage`); no query string, no `..`. */
  path?: string;
  keyFields?: string[];
  watermarkField?: string | null;
  comparedFields?: string[];
  /** Set only for a "distinct values of" derived entity (unit_of_measure) -
   * mutually exclusive with a normal `keyFields` pick (must be `["value"]`). */
  distinctOf?: string[] | null;
  /** Operator-authored cross-endpoint joins (sprint-5/10, R9) - API tasks
   * only. Omitted/`undefined` reads as "none configured yet". */
  lookups?: AutocountLookupSpec[];
  /** The row-collapsing step (sprint-5/10, R11) - API tasks only. `null`/
   * `undefined` = not configured (the common case for every entity but the
   * stock preset). */
  combine?: AutocountCombineConfig | null;
}

// ── lookups: operator-configurable cross-endpoint joins (sprint-5/10, R9) ────

/** `exact` (default) or `casefold_trim` ("Ignore case and spaces"). */
export type AutocountLookupMatch = 'exact' | 'casefold_trim';

/** One join pair - a `local` column (a source column, or an earlier lookup's
 * alias) matched against the lookup endpoint's own `remote` column. */
export interface AutocountLookupJoinPair {
  local: string;
  remote: string;
  match?: AutocountLookupMatch;
}

/** One remote column brought in under an operator-chosen alias. */
export interface AutocountLookupField {
  remote: string;
  as: string;
}

/**
 * One operator-authored cross-endpoint join (`source_config.lookups[i]`,
 * AC-10-01). ORDERED - a later lookup may join on an earlier one's alias
 * (multi-hop, AC-10-02). `as` is the lookup's own name (informational; the
 * delivered columns are `fields[].as`, not this).
 */
export interface AutocountLookupSpec {
  path: string;
  as: string;
  on: AutocountLookupJoinPair[];
  fields: AutocountLookupField[];
}

/** One lookup's Test-time result (AC-10-05) - a SAMPLE count (the preview
 * page size), never the whole population (BL-SS-222) - label it as such. */
export interface AutocountLookupPreviewResult {
  alias: string;
  matched: number;
  missed: number;
}

// ── combine rows: operator-configurable row collapsing (sprint-5/10, R11) ───

/** One ordered computed column - may name any row column, any lookup alias,
 * or an EARLIER computed alias (forward references are a save-time 422). */
export interface AutocountCombineComputed {
  alias: string;
  formula: string;
}

/** A falsy result EXCLUDES the row, with `reason` recorded on the exclusion. */
export interface AutocountCombineRequire {
  name: string;
  formula: string;
  reason: string;
}

export type AutocountCombineMeasureOp = 'sum' | 'min' | 'max' | 'count' | 'first' | 'last';

export interface AutocountCombineMeasure {
  source: string;
  op: AutocountCombineMeasureOp;
  alias: string;
}

export type AutocountCombineRoundMode = 'none' | 'half_up';

export interface AutocountCombineRound {
  measure: string;
  mode: AutocountCombineRoundMode;
  dp: number;
}

/** An ordered drop rule - the FIRST matching rule drops the group, counted
 * under its own `name`; `listRows` opts the dropped rows into the metadata
 * (capped server-side). */
export interface AutocountCombineDrop {
  name: string;
  formula: string;
  listRows?: boolean;
}

/**
 * `source_config.combine` (R11, AC-10-76) - at most ONE per task, runs after
 * every lookup and before mapping. `groupBy` becomes the task's key fields
 * (AC-10-80) - the Source tab's key picker turns into read-only chips once
 * this is set.
 */
export interface AutocountCombineConfig {
  computed: AutocountCombineComputed[];
  require: AutocountCombineRequire[];
  /** The designated quantity column - what a generic counter (e.g. a stock
   * consumer's `excludedNonzeroCount`) reads without knowing the domain. */
  measure: string;
  groupBy: string[];
  measures: AutocountCombineMeasure[];
  carry: string[];
  round: AutocountCombineRound[];
  drop: AutocountCombineDrop[];
}

/** One drop rule's Test-time outcome - PHASE 1 MOCK internal computation
 * only (`lib/autocount-combine.ts`'s `simulateCombine`), never the wire
 * shape (see `AutocountCombinePreviewResult` below). */
export interface AutocountCombineDropStat {
  count: number;
  rows?: Array<Record<string, unknown>>;
}

/**
 * The combine step's Test funnel (AC-10-82), reconciled to the SERVER
 * response shape (sprint-5/10 S5a/S5b-FE review round 4 SF-4) -
 * `POST /autocount/http/preview`'s additive `rowsIn/excludedCount/groups/
 * droppedByRule/rowsOut/roundedCount` fields (`HttpPreview` below),
 * entity-agnostic (the generic shape AC-10-81 maps onto the agreed Sorento
 * stock header names server-side). `droppedByRule` is a flat
 * `{ruleName: count}` map - no per-rule dropped-rows list and no
 * excluded-rows sample travel over the wire; the combined ROWS themselves
 * ride the SAME response's own `rows`/`columns`, not this type.
 */
export interface AutocountCombinePreviewResult {
  rowsIn: number;
  excludedCount: number;
  groups: number;
  droppedByRule: Record<string, number>;
  rowsOut: number;
  roundedCount: number;
}

/**
 * `source_config` of an `autocount_http` task, named per the UAC wire
 * contract (sprint-5/08 Definitions) - the open REST API's OWN field grammar
 * (`keyFields`/`watermarkField`/`comparedFields`/`distinctOf`, distinct from
 * the SQL task's `keyColumns`/`watermarkColumn`/`comparedColumns`/no-
 * distinct-concept). Used for local Source-tab draft state and as the
 * `previewHttp`/`GET .../http/connections` documentation shape; persisted
 * onto the SAME `AutocountEtlSourceConfig` envelope above (PHASE 1 MOCK).
 */
export interface AutocountHttpSourceConfig {
  connectionId: string | null;
  path: string;
  keyFields: string[];
  watermarkField: string | null;
  comparedFields: string[];
  distinctOf: string[] | null;
  incrementalMinutes: number;
  reconcileMode: 'interval' | 'dailyAt';
  reconcileHours: number | null;
  reconcileAt: string | null;
}

/** `GET /autocount/http/connections` - a tenant's `autocount` connections,
 * badged by auth so the Source tab / connect-company picker can label each
 * option and derive the impl without a second fetch (AC-08-15). */
export interface AutocountApiConnection {
  id: string;
  name: string;
  baseUrl: string;
  auth: AutocountConnectionAuth;
}

/** One column of an HTTP preview - a SAMPLE value, never a reported SQL type
 * (the open API carries no schema, AC-08-14). */
export interface HttpPreviewColumn {
  name: string;
  sample: unknown;
}

/**
 * `POST /autocount/http/preview` result (AC-08-14, AC-08-22 "page walk"
 * definition). `paged` = a `{TotalCount,Page,PageSize,TotalPages,Data[]}`
 * envelope (a run walks every page); `list` = a bare JSON array (one
 * request). `totalCount` is present for `paged` only.
 *
 * `task` (sprint-5/08 review round 7) - the task AFTER stamping, present
 * only when the request named both `companyId`/`entityType` and the
 * preview succeeded (the SAME gate the backend's own stamping applies).
 * The Source tab's Test button adopts this directly (`apply()`) instead of
 * a second GET, which used to race a concurrent Save (round 6's `reload()`
 * bug - see `task-editor-view.tsx`'s `onHttpPreviewSuccess`).
 */
export interface HttpPreview {
  envelope: 'paged' | 'list';
  totalCount?: number;
  columns: HttpPreviewColumn[];
  rows: Array<Record<string, unknown>>;
  durationMs: number;
  task?: AutocountEtlTask;
  /** Per-lookup `{alias, matched, missed}` counts (AC-10-05) - a SAMPLE,
   * never the whole population. Empty when the preview carried no lookups. */
  lookups?: AutocountLookupPreviewResult[];
  /**
   * sprint-5/10 S5a follow-up (AC-10-82) - the combine funnel's six counts,
   * flat on the response exactly like the backend's own additive
   * `HttpPreviewResponse` fields (`schemas.py`) - present ONLY when the
   * request carried a `combine` block; `rows`/`columns` above are then the
   * COMBINED shape, not the pre-combine sample. Every field is `undefined`
   * for a plain (no-combine) preview.
   */
  rowsIn?: number;
  excludedCount?: number;
  groups?: number;
  droppedByRule?: Record<string, number>;
  rowsOut?: number;
  roundedCount?: number;
  /**
   * sprint-5/10 S5b-FE review round 1 (AC-10-82/AC-10-40) - present ONLY
   * when the request carried a `combine` block (`schemas.py`'s
   * `HttpPreviewResponse.preCombineColumns`): the PRE-combine column set
   * (raw source + lookup aliases + computed aliases), i.e. what
   * `columns`/`rows` above WOULD have been without the combine step. The
   * Source tab's key/watermark/compared/Lookups/Combine pickers read THIS
   * (never `columns`, which is the COMBINED shape whenever this is set, and
   * never the echoed `task`, which a brand-new entity's first Test carries
   * none of yet) - `source-tab.tsx`'s `httpPreviewColumns`. `null`/absent
   * for a plain (no-combine) preview, where `columns` above already IS the
   * pre-combine set.
   */
  preCombineColumns?: string[] | null;
  /**
   * sprint-5/10 confirm round 2 (AC-10-01/AC-10-09) - the RAW columns of the
   * walked endpoint: never a lookup alias, never a combine computed alias,
   * and (unlike `preCombineColumns`) present on EVERY response, lookups or
   * not, combine or not. `columns` above is by design the MERGED shape (raw
   * UNION every alias the REQUEST's lookups carried), so it can never serve
   * as the Lookups editor's "names already taken" set - an alias the very
   * same Test introduced collided with itself. Optional only for the wire's
   * own tolerance: a consumer reading it falls back to an EMPTY set (nothing
   * is taken), NEVER to `columns`.
   */
  rawColumns?: string[];
}

/** `POST /autocount/http/preview` body. */
export interface HttpPreviewInput {
  connectionId: string;
  path: string;
  /** Project the response's listed fields to distinct `{value}` rows (the
   * `unit_of_measure` preset - AC-08-16 D6). */
  distinctOf?: string[];
  /**
   * When both are given, a clean preview also stamps `resultColumns`/
   * `lastPreviewAt` on the named task (AC-08-14, sprint-5/08 review round 1
   * B3) - the SAME "Test the endpoint" ceremony the SQL tab's Test Query
   * button already performs, and what makes the Source tab's own Test
   * button satisfy the activate-once gate without a second "Preview"
   * ceremony on the Review & Activate tab.
   */
  companyId?: string;
  entityType?: string;
  /** Operator-authored cross-endpoint joins, applied in order over the
   * sampled page (sprint-5/10, AC-10-05). */
  lookups?: AutocountLookupSpec[];
  /** The operator's DRAFT combine step (sprint-5/10 S5a follow-up,
   * AC-10-82) - sent ONLY when the task carries one; the response's
   * `rows`/`columns` become the COMBINED shape and the funnel fields above
   * populate. */
  combine?: AutocountCombineConfig | null;
}

/**
 * `GET /autocount/companies/{id}/entities/{entityType}/etl-task` - one
 * per-(company, entity) DB extraction task, anchored on `ac_entity_config`
 * (decision Q13 - no free-form task entity).
 */
export interface AutocountEtlTask {
  companyId: string;
  entityType: string;
  etlStatus: AutocountEtlStatus;
  activatedAt: string | null; // ISO Z
  /**
   * Which task grammar `sourceConfig` is populated as (sprint-5/08, D13) -
   * `sql_db` (default; every task before this plan), `autocount_http`, or
   * `autocount_read` (S9, review round 1 - the pre-existing vendor-API
   * grammar the backend already returns for GRN/supplier/customer tasks;
   * omitting it from this union was silently narrowing a real backend
   * value down to `undefined` at the type boundary). Optional/absent reads
   * as `sql_db` everywhere (back-compat with every fixture/task built
   * before this field existed).
   */
  sourceImpl?: 'sql_db' | 'autocount_http' | 'autocount_read';
  sourceConfig: AutocountEtlSourceConfig;
  /**
   * Result column names of the SAVED query - derived server-side from the
   * validation preview each save runs (AC-22-11), so the Mapping tab can offer
   * them as the source picker (AC-22-09) without re-running the query. Empty
   * until a query has been saved.
   */
  resultColumns: string[];
  /**
   * When the last SUCCESSFUL dry-run preview completed (AC-22-18). Cleared by
   * every config save - a preview of a superseded query must never unlock
   * Activate. Null = Activate withheld.
   */
  lastPreviewAt: string | null; // ISO Z
  /**
   * The last preview's genuinely-FAILED prediction count (S5 review
   * SHOULD-FIX 4b) - distinct from `retryable`, which stays activatable (a
   * dependency-order carry-over, AC-22-23). A preview that COMPLETES is not
   * by itself proof the task is safe to activate.
   */
  lastPreviewFailedCount: number | null;
  lastRunAt: string | null; // ISO Z
  /**
   * The last run's TASK-LEVEL error (AC-22-19 - repeated delivery failures
   * surface here, never silently). A Sorento anchor 422 lands here with its
   * code, never as a per-record failure (Appendix A6).
   */
  lastRunError: string | null;
  lastRunErrorCode: AutocountAnchorErrorCode | string | null;
  /**
   * When the scheduler will next fire each cadence (plan 22 §2.6, slice S3).
   * Read-only, server-stamped (`EtlService.next_run_times`); null while the
   * task is not `active` (draft and paused carry no next run - pause clears
   * them, activate/resume arms them); recomputed on every PUT while active.
   */
  nextIncrementalAt: string | null; // ISO Z
  nextReconcileAt: string | null; // ISO Z
  /**
   * sprint-5/08 (AC-08-33/AC-08-20 S5) - non-null ONLY for a `brand` task
   * whose consumer does not yet accept brands (the live
   * `fetch_contract_detail` -> `sorento_supports_entity` probe, read the
   * moment the task loads rather than only after Preview/Run). Drives the
   * Review & Activate banner ("Consumer contract 2.2 - brands land when 2.3
   * is deployed"). Optional/absent reads as `null` (back-compat with every
   * fixture/task built before this field existed, same convention as
   * `sourceImpl` above) - nothing to warn about.
   */
  brandContractGate?: AutocountBrandContractGate | null;
  /**
   * `push` (default) or `pull` (sprint-5/10, D1/D2) - mirrors the entity
   * config's own field so the task editor's Schedule/Activate tabs need no
   * second fetch. Optional/absent reads as `push` (back-compat with a
   * fixture built before this field existed).
   */
  deliveryMode?: AutocountDeliveryMode;
  /**
   * sprint-5/10 (AC-10-69) - the GENERALISED contract gate (entity +
   * version + requiredVersion), landing beside `brandContractGate` on the
   * wire (S3 backend). `brandContractGate` is unchanged and NOT folded into
   * this on the frontend yet - no UI reads this field in S2; declared now
   * so the type compiles against the real backend response once S3 ships
   * it. Optional/absent (every fixture/task built before this field
   * existed, and every entity the gate does not apply to).
   */
  contractGate?: AutocountContractGate | null;
  /**
   * sprint-5/10 review round 4 (SF-4) - the COMBINED, POST-GROUP schema a
   * combine-carrying task's own rows carry (`groupBy + carry +
   * measures[].alias`); `[]`/absent when no combine step is configured
   * (back-compat with every fixture/task built before this field existed).
   * ADDITIVE alongside `resultColumns` above (the pre-combine raw/lookup
   * set, unchanged) - the Mapping tab's source picker reads THIS instead of
   * `resultColumns` once it is non-empty (`task-editor-view.tsx`).
   */
  combineOutputColumns?: string[];
  /**
   * sprint-5/11 (AC-11-23/27) - the id of this task's IN-FLIGHT preview job,
   * if any (`ac_entity_config.preview_job_id`). Lets a remounted editor
   * re-attach to a running Test/Run-preview job instead of starting a
   * second one. `null`/absent (every fixture built before this field
   * existed) = no preview in flight.
   */
  previewJobId?: string | null;
}

/** `AutocountEtlTask.brandContractGate` (AC-08-33/AC-08-20 S5). `version` is
 * `null` only when the consumer could not be reached (advisory). */
export interface AutocountBrandContractGate {
  version: number | null;
  requiredVersion: number;
}

/** `AutocountEtlTask.contractGate` (sprint-5/10, AC-10-69) - the same
 * nullable-version shape as `AutocountBrandContractGate`, generalised with
 * the entity it gates (`product` today; `stock_balance` at 2.5, S7). */
export interface AutocountContractGate {
  entity: string;
  version: number | null;
  requiredVersion: number;
}

/** `PUT .../etl-task` body - replaces the task's source config (draft save). */
export interface AutocountEtlTaskUpdate {
  sourceConfig: AutocountEtlSourceConfig;
  /**
   * The task's Source (sprint-5/08, D13) - present when the operator's
   * toggle derives `sql_db` or `autocount_http`; omitted when the picked
   * connection is basic-auth (that save goes through
   * `updateEntityConfig({sourceImpl:'autocount_read'})` instead, there being
   * no task at all on that path).
   */
  sourceImpl?: 'sql_db' | 'autocount_http';
}

// ── activation gate + runs (plan 22, slice S2 - AC-22-17/18/19, Appendix A6) ──

/**
 * Sorento's company-anchor 422 codes (Appendix A6). Any of these on a preview
 * or a run is a TASK-level configuration error - fix the company's Sorento
 * company code - and is never attributed to a record.
 */
export type AutocountAnchorErrorCode =
  | 'COMPANY_ANCHOR_REQUIRED'
  | 'UNKNOWN_COMPANY'
  | 'COMPANY_ANCHOR_AMBIGUOUS'
  | 'COMPANY_BINDING_INVALID';

/**
 * The structured `detail` of a task-level 422 from `POST .../etl-task/preview`
 * (`ApiError.detail`) - the anchor error translated 1:1 from Sorento's body.
 */
export interface AutocountEtlTaskError {
  code: AutocountAnchorErrorCode | string;
  message: string;
}

/**
 * `POST .../etl-task/preview` - the initial-load dry run against Sorento
 * (writes nothing). `preview` is the SAME shape the batch review renders
 * (`PreviewPanel`); `task` is the task after the preview (its `lastPreviewAt`
 * stamped when the dry run completed).
 */
export interface AutocountEtlPreviewResult {
  task: AutocountEtlTask;
  preview: AutocountPreview;
}

// ── preview job (sprint-5/11, Group B - AC-11-20..31) ─────────────────────────
//
// The Cloudflare-safe non-blocking preview: the Source tab's Test and Review &
// Activate's Run preview each start ONE job kind (`autocount_source_preview`,
// owner ruling R3) with a `scope` - `sample` runs today's `preview_http`
// unchanged, `full` runs today's `preview_task` unchanged. The frontend polls
// `GET /autocount/previews/{jobId}` instead of awaiting the walk. PHASE 1 MOCK
// (S3) - `autocount-service.mock.ts` is the backend spec until S4 lands the
// real `autocount_source_preview` job + routes.

/** `sample` = the Source tab's Test (page 1 + lookups, `preview_http`);
 * `full` = Review & Activate's Run preview (the whole walk + mapping +
 * Sorento dry run, `preview_task`). ONE job kind, two scopes (D5) - one
 * progress UI, one cancel path. */
export type AutocountPreviewJobScope = 'sample' | 'full';

/** Wire status of a preview job (AC-11-22). `done`/`failed`/`cancelled` are
 * terminal. */
export type AutocountPreviewJobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

/** Rides the SAME progress mechanism as a pull-snapshot build
 * (`AutocountPullSnapshotProgress`, AC-11-40) - every field absent whenever
 * it is not known yet, never guessed. */
export interface AutocountPreviewJobProgress {
  stage: string | null;
  pagesDone: number | null;
  pagesTotal: number | null;
}

/** The `sample` scope's landed result - the SAME `HttpPreview` shape the
 * synchronous route used to return, echoing the stamped task when the save
 * gate applies (AC-11-26). */
export interface AutocountPreviewJobSampleResult {
  scope: 'sample';
  preview: HttpPreview;
}

/** The `full` scope's landed result - the SAME shape
 * `POST .../etl-task/preview` used to return. */
export interface AutocountPreviewJobFullResult {
  scope: 'full';
  task: AutocountEtlTask;
  preview: AutocountPreview;
}

export type AutocountPreviewJobResult = AutocountPreviewJobSampleResult | AutocountPreviewJobFullResult;

/**
 * `GET /autocount/previews/{jobId}` (AC-11-22/27). `error` is an
 * operator-safe failure sentence (AC-11-25); `taskError` is a `full`-scope
 * Sorento anchor error (Appendix A6) - a TASK-level configuration problem,
 * rendered as its own banner rather than a generic failure, exactly as the
 * synchronous route's 422 used to be read.
 */
export interface AutocountPreviewJob {
  id: string;
  scope: AutocountPreviewJobScope;
  status: AutocountPreviewJobStatus;
  progress: AutocountPreviewJobProgress | null;
  result: AutocountPreviewJobResult | null;
  error: string | null;
  taskError: AutocountEtlTaskError | null;
  /** A `sample`-scope 422 named a field (`connectionId`/`path`) - carried so
   * the Source tab can still show it inline, exactly as the synchronous
   * route's 422 used to. Empty/absent for every other failure. */
  fieldErrors?: Record<string, string>;
  createdAt: string | null; // ISO Z
}

/** `POST /autocount/http/preview` once it becomes a job start (AC-11-21/22) -
 * the Source tab's `sample` scope. */
export interface AutocountPreviewJobSampleInput {
  scope: 'sample';
  companyId: string;
  entityType: string;
  connectionId: string;
  path: string;
  distinctOf?: string[];
  lookups?: AutocountLookupSpec[];
  combine?: AutocountCombineConfig | null;
}

/** `POST .../etl-task/preview` once it becomes a job start (AC-11-21/22) -
 * Review & Activate's `full` scope. */
export interface AutocountPreviewJobFullInput {
  scope: 'full';
  companyId: string;
  entityType: string;
}

export type AutocountPreviewJobStartInput = AutocountPreviewJobSampleInput | AutocountPreviewJobFullInput;

/** 202 response of either POST (AC-11-22). */
export interface AutocountPreviewJobStart {
  jobId: string;
  status: AutocountPreviewJobStatus;
}

/** `POST .../etl-task/run` - the manual run just enqueued (eager inline in dev). */
export interface AutocountEtlRunStart {
  runId: string;
  jobId: string;
  status: AutocountJobStatus | string;
  /** The task after the run (status/last-error refreshed when it ran inline). */
  task: AutocountEtlTask;
}

/**
 * `POST .../etl-task/repush` (plan sprint-5/07, AC-07-13..19) - clears this
 * task's tracked rows (`ac_row_hash`) so the next reconcile classifies every
 * source row as an add and re-pushes it. `nextReconcileAt` mirrors what the
 * server armed: `now(utc)` for an `active` task (the next sweep claims a
 * reconcile), `null` for a `paused` one (nothing scheduled until resumed).
 * `status` is the task's `etlStatus`, unchanged by this call.
 */
export interface AutocountEtlRepushResult {
  clearedCount: number;
  nextReconcileAt: string | null; // ISO Z
  status: AutocountEtlStatus;
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

// ── human-invoked pull (sprint-5/10) ─────────────────────────────────────────

/** A per (company, entity) choice (`ac_entity_config.delivery_mode`, D1/D2):
 * `push` runs the task on the schedule as today; `pull` never auto-pushes -
 * a consumer/operator request builds a snapshot on demand instead. */
export type AutocountDeliveryMode = 'push' | 'pull';

/** `PUT .../entities/{entityType}/delivery-mode` body (AC-10-11). */
export interface AutocountDeliveryModeUpdate {
  deliveryMode: AutocountDeliveryMode;
}

// ── pull snapshots (D6/D7/D8) ────────────────────────────────────────────────

export type AutocountPullSnapshotStatus = 'building' | 'ready' | 'failed';

/** `entity` on the wire is `products`/`stock_balances`; this side keeps the
 * internal singular keys (`product`/`stock_balance`) throughout. */
export type AutocountPullEntity = 'product' | 'stock_balance';

/** A cheap, optional build-progress hint (AC-10-87) - absent whenever it is
 * not known; never a percentage. */
export interface AutocountPullSnapshotProgress {
  pagesDone: number;
  pagesTotal: number;
  stage: string;
}

/** One record the extraction read but could not deliver (R6). Shape is per
 * entity (`source_ref`/`code` for products, `item_code`/`location_code`/
 * `uom`/`qty` for stock) - kept as an open bag rather than a union so a new
 * entity's shape needs no FE type change. */
export interface AutocountPullExcludedRow {
  [key: string]: unknown;
  reason: string;
}

/** One negative-pair row (stock only, AC-10-42). */
export interface AutocountPullNegativePair {
  item_code: string;
  location_code: string;
  qty: number;
}

/**
 * One snapshot's header (AC-10-32) - the ONE place the entity-specific
 * counters appear. Product/stock counters are optional so a single type
 * covers both entities without a discriminated union the UI must branch on
 * for every read; `entityType` is what actually decides which counters are
 * meaningful.
 */
export interface AutocountPullSnapshot {
  id: string;
  entityType: AutocountPullEntity | string;
  companyId: string;
  companyCode: string;
  status: AutocountPullSnapshotStatus;
  requestedVia: 'operator' | 'gateway';
  createdAt: string | null; // ISO Z
  extractedAt: string | null; // ISO Z
  expiresAt: string | null; // ISO Z
  recordCount: number;
  complete: boolean;
  contentHash: string | null;
  sourcePageSize: number | null;
  /** Absent whenever it is not known (AC-10-87) - never guessed. */
  progress?: AutocountPullSnapshotProgress | null;
  error?: { code: string; message: string } | null;
  excludedCount: number;
  excludedRows: AutocountPullExcludedRow[];
  // product-only (AC-10-63)
  zeroListPriceCount?: number;
  negativeListPriceCount?: number;
  enrichMissCount?: number;
  // stock-only (AC-10-42/43/66/81)
  zeroPairs?: number;
  negativePairs?: number;
  fractionalPairs?: number;
  excludedNonzeroCount?: number;
  negativePairList?: AutocountPullNegativePair[];
}

/** `GET .../rows?page=&pageSize=` - one page, served exactly as stored
 * (AC-10-33). Row shape is per entity (`CanonicalProduct.sink_payload()` /
 * the stock row shape, Appendix A4), so this stays `Record<string, unknown>`
 * like every other preview grid's row type. */
export interface AutocountPullSnapshotRowsPage {
  snapshotId: string;
  page: number;
  pageSize: number;
  totalPages: number;
  recordCount: number;
  rows: Array<Record<string, unknown>>;
}

/** `GET/POST /autocount/pull/keys` list item (AC-10-27/37). Never carries the
 * plaintext - that is returned ONCE, on issue, in `AutocountPullApiKeyIssued`. */
export interface AutocountPullApiKey {
  id: string;
  name: string;
  companyIds: string[];
  keyPrefix: string;
  createdAt: string | null; // ISO Z
  lastUsedAt: string | null; // ISO Z
  revokedAt: string | null; // ISO Z
}

/** `POST /autocount/pull/keys` body - name + the explicit company set. */
export interface AutocountPullApiKeyCreateInput {
  name: string;
  companyIds: string[];
}

/** Issue result - `plaintext` is shown exactly ONCE (AC-10-28), never
 * persisted or re-derivable afterwards. */
export interface AutocountPullApiKeyIssued {
  key: AutocountPullApiKey;
  plaintext: string;
}
