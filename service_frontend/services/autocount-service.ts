/**
 * AutoCount ESB service (sprint-4/13, slice 1) - the boundary the
 * `/autocount/*` surfaces talk to via hooks. The interface IS the backend
 * contract: `modules/autocount/routers/{companies,sync}.py`.
 *
 * The shipped binding is `.real` - the whole surface, S2 included, is backed
 * by FastAPI - wrapped in ONE tiny, tagged PHASE 1 MOCK overlay
 * (`withPhase1NextRunMock`, plan 22 S3) for the two read-only fields the
 * backend has not put on the wire yet (see the doc block above `listSqlConnections`
 * for what it does and does not touch). A `.mock` sibling also exists as
 * frontend-first scaffolding for the dry-run review states (previewable /
 * not-previewable / failure) and the Vitest suite (the house service-trio
 * pattern).
 *
 * Permission gates (module CSV, granted to tenant Admin by `AppStoreService`
 * on install): `autocount.companies.read/manage`, `autocount.sync.read/run`.
 */
import type {
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountEntityConfigUpdate,
  AutocountEtlPreviewResult,
  AutocountEtlRunStart,
  AutocountEtlTask,
  AutocountEtlTaskUpdate,
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateResult,
  AutocountSinkTargetInput,
  AutocountSqlConnection,
  AutocountSqlPreview,
  AutocountSqlSchema,
  AutocountStagedList,
  AutocountStagedQuery,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import { realAutocountService } from './autocount-service.real';
import { withPhase1NextRunMock } from './autocount-service.mock';

export interface AutocountListQuery {
  page?: number; // 0-based
  pageSize?: number;
}

export interface AutocountService {
  /** Paginated companies (`GET /autocount/companies`). */
  listCompanies(query?: AutocountListQuery): Promise<ListResult<AutocountCompany>>;
  /** One company + its per-entity sync config (`GET /autocount/companies/{id}`). */
  getCompany(id: string): Promise<AutocountCompanyDetail>;
  /**
   * Register a company by DISCOVERING it from its connection
   * (`POST /autocount/companies`). The backend signs in and reads the company
   * name back - there is deliberately no company field to supply.
   */
  createCompany(input: AutocountCompanyCreateInput): Promise<AutocountCompany>;
  /**
   * Adjust one entity's sync configuration
   * (`PATCH /autocount/companies/{id}/entities/{entityType}`). Narrow by
   * design - the initial lookback window, and (plan 22 S2) the `sourceImpl`
   * switch between the API path and the DB task.
   */
  updateEntityConfig(
    companyId: string,
    entityType: string,
    input: AutocountEntityConfigUpdate,
  ): Promise<AutocountEntityConfig>;
  /** Trigger a manual sync (`POST /autocount/companies/{id}/sync`). */
  syncNow(companyId: string, entityType: string): Promise<AutocountSyncJob>;
  /**
   * Re-open an entity's first-run window by RESETTING its watermark
   * (`POST /autocount/companies/{id}/entities/{entityType}/refetch`). The
   * deliberate, confirmed act that re-widens a spent window (AC-15-30) - the
   * next sync re-reads from `initialLookbackDays` again. Distinct from editing
   * the window, which is a no-op once superseded.
   */
  refetchHistory(
    companyId: string,
    entityType: string,
  ): Promise<AutocountEntityConfig>;
  /**
   * The Review list - sync batches for the tenant, newest first
   * (`GET /autocount/jobs`, AC-15-02). Server-paginated + status-segment
   * filtered; NEVER an unbounded fetch.
   */
  listJobs(query?: AutocountJobListQuery): Promise<ListResult<AutocountSyncJobBatch>>;
  /** Run history for a company (`GET /autocount/companies/{id}/runs`). */
  listRuns(
    companyId: string,
    query?: AutocountListQuery & { entityType?: string },
  ): Promise<ListResult<AutocountSyncRun>>;
  /**
   * Staged records + per-record diffs (`GET /autocount/jobs/{id}/staged`).
   * Server-paginated + searchable + `changed`-filtered (AC-15-10) - never an
   * all-rows fetch. Omitting the query returns the first page.
   */
  listStaged(
    jobId: string,
    query?: AutocountStagedQuery,
  ): Promise<AutocountStagedList>;
  /**
   * Dry-run the batch against the consumer, writing nothing
   * (`POST /autocount/jobs/{id}/preview`). Returns the consumer's own
   * prediction - the overwrite gate (AC-14-20/21). A logging-sink company
   * yields a "not previewable" shape; an unreachable consumer throws (HTTP 502).
   */
  preview(jobId: string): Promise<AutocountPreviewResult>;
  /** Push the batch (`POST /autocount/jobs/{id}/approve`) - idempotent. */
  approve(jobId: string): Promise<AutocountApprovalResult>;
  /** Close without pushing (`POST /autocount/jobs/{id}/discard`). */
  discard(jobId: string): Promise<AutocountApprovalResult>;
  /**
   * Point a company at a push target
   * (`PATCH /autocount/companies/{id}/sink-target`). `logging` clears the
   * target; `sorento` requires a `sinkConnectionId` AND (plan 22 S2, Appendix
   * A6) a `sorentoCompanyCode` - the company anchor Sorento demands on every
   * call; blank with `sorento` = 422 `{fieldErrors: {sorentoCompanyCode}}`.
   */
  updateSinkTarget(
    companyId: string,
    input: AutocountSinkTargetInput,
  ): Promise<AutocountCompany>;
  /**
   * One entity's current field mappings + the source/target catalogs the
   * editor's pickers need (`GET /autocount/companies/{id}/entities/{entityType}/mapping`,
   * AC-15-40).
   */
  getMapping(companyId: string, entityType: string): Promise<AutocountMappingView>;
  /**
   * Replace the entity's deliverable field mappings
   * (`PUT .../entities/{entityType}/mapping`, AC-15-41). The server GUARDS every
   * row (accepted Sorento target, non-blank source, known transform, no
   * duplicate target) - a rejected row is a 422, never a silent drop.
   */
  updateMapping(
    companyId: string,
    entityType: string,
    input: AutocountMappingUpdate,
  ): Promise<AutocountMappingView>;
  /**
   * Server-authoritative single-formula eval
   * (`POST .../mapping/test-formula`, AC-16-21) - the parity check behind the
   * builder's live client preview. A bad formula/value comes back as
   * `{ ok: false, error }`, never a throw. Writes nothing.
   */
  testFormula(
    companyId: string,
    entityType: string,
    formula: string,
    value: unknown,
  ): Promise<AutocountFormulaTestResult>;
  /**
   * Run the REAL MappingEngine over a MOCK AutoCount record
   * (`POST .../mapping/simulate`, AC-16-30) → the projected Sorento record +
   * per-field results. `rows` (optional) previews UNSAVED draft edits. Writes
   * NOTHING - pure transform preview, distinct from the slice-14 Sorento dry-run.
   */
  simulateMapping(
    companyId: string,
    entityType: string,
    record: Record<string, unknown>,
    rows?: AutocountMappingWriteRow[],
  ): Promise<AutocountSimulateResult>;

  // ── direct-DB ETL (plan 22, slice S1 - AC-22-04..07/11) ────────────────────
  //
  // BACKEND CONTRACT (phase 2 must match this EXACTLY - the mock is the spec):
  //
  //   GET  /autocount/sql/connections
  //        → AutocountSqlConnection[]  (tenant's `sql_database` connections
  //          ONLY - resolved tenant+provider scoped, never bare get-by-id).
  //        Gated `autocount.companies.manage`.
  //
  //   GET  /autocount/sql/connections/{connectionId}/schema[?refresh=true]
  //        → AutocountSqlSchema  (schemas → tables → columns via dialect-
  //          agnostic introspection; CACHED per connection server-side,
  //          `refresh=true` busts the cache - AC-22-05). A connection that is
  //          not the tenant's / not `sql_database` = 404. A connect failure =
  //          502 with a SANITIZED message (no credentials, no DSN, no raw
  //          driver stack - AC-22-30).
  //        Gated `autocount.companies.manage`.
  //
  //   POST /autocount/sql/preview  {connectionId, query}
  //        → AutocountSqlPreview  (≤ 100 rows, dialect-appropriate wrapping,
  //          column names + types - AC-22-06). Non-SELECT / multi-statement =
  //          422 BEFORE touching the source (AC-22-03); a failing query = 400
  //          with the DB error sanitized; a bounded per-query timeout applies.
  //        Gated `autocount.companies.manage`.
  //
  //   GET  /autocount/companies/{id}/entities/{entityType}/etl-task
  //        → AutocountEtlTask  (anchored on `ac_entity_config.source_config`;
  //          a never-configured entity returns a DRAFT task with defaults, not
  //          a 404 - the editor is the create surface).
  //        Gated `autocount.companies.read`.
  //
  //   PUT  /autocount/companies/{id}/entities/{entityType}/etl-task
  //        {sourceConfig} → AutocountEtlTask  (draft save - replaces the
  //          source config). Validation (AC-22-11): provided key/watermark/
  //          compared columns must exist in a fresh preview's result columns
  //          and the watermark must be orderable → 422 {fieldErrors}; empty
  //          keyColumns is allowed while `etlStatus === 'draft'` (activation,
  //          S2, is the hard gate). `connectionId` is re-validated against the
  //          tenant on every use.
  //        Gated `autocount.companies.manage`.

  /** The tenant's SQL-database connections the task editor may pick from. */
  listSqlConnections(): Promise<AutocountSqlConnection[]>;
  /** Cached schema tree for one connection; `refresh` busts the cache. */
  getSqlSchema(
    connectionId: string,
    opts?: { refresh?: boolean },
  ): Promise<AutocountSqlSchema>;
  /** Run a candidate SELECT against the source, capped at 100 rows. */
  previewSqlQuery(connectionId: string, query: string): Promise<AutocountSqlPreview>;
  /** One entity's DB extraction task (draft defaults when unconfigured). */
  getEtlTask(companyId: string, entityType: string): Promise<AutocountEtlTask>;
  /** Draft-save the task's source config (422 {fieldErrors} on bad columns). */
  updateEtlTask(
    companyId: string,
    entityType: string,
    input: AutocountEtlTaskUpdate,
  ): Promise<AutocountEtlTask>;

  // ── direct-DB ETL (plan 22, slice S2 - AC-22-08..11/17/18/19, Appendix A6) ──
  //
  // BACKEND CONTRACT (phase 2 must match this EXACTLY - the mock is the spec).
  // Additions to EXISTING routes first:
  //
  //   PATCH /autocount/companies/{id}/entities/{entityType}
  //        body gains `sourceImpl: 'autocount_read' | 'sql_db'` (AC-22-08).
  //        Switching keeps the task's `source_config` (a configured query is
  //        never discarded); switching an ACTIVE task to `autocount_read`
  //        pauses it (never left auto-pushing under a source that no longer
  //        runs it). Unknown value = 422.
  //
  //   PATCH /autocount/companies/{id}/sink-target
  //        body gains `sorentoCompanyCode` (→ `ac_company.sorento_company_code`,
  //        new column, backfill NULL). REQUIRED with `sinkImpl='sorento'`
  //        (422 `{fieldErrors: {sorentoCompanyCode}}`); stored trimmed; nulled
  //        with `logging`. `CompanyItem` echoes it as `sorentoCompanyCode`.
  //        `SorentoSink` sends it as the top-level `companyCode` on EVERY call.
  //
  //   GET/PUT .../etl-task  →  AutocountEtlTask gains (all read-only on the wire):
  //        `resultColumns[]` (the validation preview's column names, stored
  //        at PUT), `lastPreviewAt` (stamped by a completed dry run, CLEARED
  //        by every PUT), `lastRunAt`, `lastRunError`, `lastRunErrorCode`
  //        (the task-level error of the latest run - anchor 422s land here,
  //        never per record).
  //
  //   GET/PUT .../etl-task (plan 22 S3, AC-22-12..17) → AutocountEtlTask ALSO
  //        gains `nextIncrementalAt`/`nextReconcileAt` (read-only, recomputed
  //        by every PUT/activate/pause/resume/run - `EtlService.next_run_times`
  //        ALREADY computes + stores them server-side, `EtlTaskResponse` just
  //        does not carry them on the wire yet; the schedule fields themselves
  //        (`incrementalMinutes`/`reconcileMode`/`reconcileHours`/`reconcileAt`)
  //        already round-trip through the existing PUT + its 422 fieldErrors -
  //        `services/autocount-service.mock.ts withPhase1NextRunMock` is the
  //        tiny stand-in for the two missing read-only fields only).
  //
  //   GET  /autocount/companies/{id}/runs  →  AutocountSyncRun gains the §2.7
  //        cost columns `mode`, `rowsScanned`, `addedCount`, `updatedCount`,
  //        `deletedCount`, `durationMs`, `skipReason` (API-path runs report
  //        `mode='manual'`, zero deletes). `jobId` becomes nullable (skipped).
  //
  // New routes (all under /autocount/companies/{id}/entities/{entityType}/etl-task):
  //
  //   POST .../preview
  //        → AutocountEtlPreviewResult  (initial-load dry run: extract the
  //          saved query, map, `SorentoSink` `?dry_run=true`; writes NOTHING;
  //          `preview` = the SAME shape as `POST /autocount/jobs/{id}/preview`;
  //          `task.lastPreviewAt` stamped when the dry run completed).
  //          Logging sink → `previewable: false`. Unreachable consumer → 502.
  //          Sorento anchor 422 (COMPANY_ANCHOR_REQUIRED / UNKNOWN_COMPANY /
  //          COMPANY_ANCHOR_AMBIGUOUS) → 422 `{detail: {code, message}, message}`
  //          - a TASK-level error, never a per-record `failed` (Appendix A6).
  //          No query / no key columns → 409.
  //        Gated `autocount.sync.run`.
  //
  //   POST .../activate
  //        → AutocountEtlTask  (`draft|paused` → `active`, `activatedAt`
  //          stamped, next-run times armed). 409 unless `lastPreviewAt` is set
  //          (AC-22-18 - the gate is server-side too) or the company has no
  //          Sorento company code.
  //        Gated `autocount.companies.manage`.
  //
  //   POST .../pause    → AutocountEtlTask  (`active` → `paused`; sweep stops
  //          dispatching, in-flight runs finish; 409 unless active).
  //   POST .../resume   → AutocountEtlTask  (`paused` → `active`, NO
  //          re-preview needed - AC-22-19; 409 unless paused).
  //        Both gated `autocount.companies.manage`.
  //
  //   POST .../run
  //        → AutocountEtlRunStart  (enqueue ONE `autocount_sync` job with
  //          `mode='manual'` - the same pipeline the sweep uses; eager inline
  //          in dev so `task` comes back refreshed). 409 unless `active`, or
  //          while a run for this (company, entity) is still executing.
  //        Gated `autocount.sync.run`.
  //
  //   GET  .../runs?page=&page_size=
  //        → ListResult<AutocountSyncRun>  (this entity's history, newest
  //          first, page_size ≤ 200; skipped ticks included with `skipReason`).
  //        Gated `autocount.sync.read`.

  /** Initial-load dry run against Sorento (writes nothing). */
  previewEtlTask(companyId: string, entityType: string): Promise<AutocountEtlPreviewResult>;
  /** The activate-once gate: draft/paused → active (409 without a preview). */
  activateEtlTask(companyId: string, entityType: string): Promise<AutocountEtlTask>;
  /** active → paused (in-flight runs finish). */
  pauseEtlTask(companyId: string, entityType: string): Promise<AutocountEtlTask>;
  /** paused → active, no re-activation ceremony. */
  resumeEtlTask(companyId: string, entityType: string): Promise<AutocountEtlTask>;
  /** Enqueue a manual run now (active tasks only). */
  runEtlTaskNow(companyId: string, entityType: string): Promise<AutocountEtlRunStart>;
  /** This entity's run history, newest first. */
  listEtlRuns(
    companyId: string,
    entityType: string,
    query?: AutocountListQuery,
  ): Promise<ListResult<AutocountSyncRun>>;
}

// The S2 backend is LIVE, so the full phase-1 overlay (`withPhase1EtlMock`) is
// gone from the shipped binding (the swap the Definition-of-Done gate
// demands). PHASE 1 MOCK (plan 22 S3, tiny + tagged - see the doc block
// above): `withPhase1NextRunMock` stamps ONLY `nextIncrementalAt`/
// `nextReconcileAt` on top of every real response; everything else is real
// data untouched. Delete this wrapper the moment the S3 backend adds the two
// fields to `EtlTaskResponse`.
export const autocountService: AutocountService = withPhase1NextRunMock(realAutocountService);
