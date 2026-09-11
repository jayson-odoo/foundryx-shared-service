/**
 * AutoCount ESB service (sprint-4/13, slice 1) - the boundary the
 * `/autocount/*` surfaces talk to via hooks. The interface IS the backend
 * contract: `modules/autocount/routers/{companies,sync}.py`.
 *
 * The shipped binding is the BARE `.real` service - the whole surface (S1-S3)
 * is backed by FastAPI end to end, including the schedule fields
 * (`nextIncrementalAt`/`nextReconcileAt`, plan 22 S3). A `.mock` sibling also
 * exists as frontend-first scaffolding for the dry-run review states
 * (previewable / not-previewable / failure) and the Vitest suite (the house
 * service-trio pattern).
 *
 * Permission gates (module CSV, granted to tenant Admin by `AppStoreService`
 * on install): `autocount.companies.read/manage`, `autocount.sync.read/run`.
 */
import type {
  AutocountApiConnection,
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountEntityConfigUpdate,
  AutocountEtlPreviewResult,
  AutocountEtlRepushResult,
  AutocountEtlRunStart,
  AutocountEtlTask,
  AutocountEtlTaskUpdate,
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingPreset,
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
  HttpPreview,
  HttpPreviewInput,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import { realAutocountService } from './autocount-service.real';
// `mockAutocountService` stays imported by the Vitest suite directly
// (the house service-trio pattern) - no need to import it here just to
// keep it compiling.

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
   * (`POST /autocount/companies`) - there is deliberately no company field to
   * supply. The backend branches on the connection's PROVIDER (plan sprint-5/01,
   * AC-01-01): an `autocount` connection signs in and reads the company name
   * back; a `sql_database` connection derives the identity from its
   * `config.database`, verified by a live probe. 409 names the company already
   * holding the database/connection; 422 `{fieldErrors: {connectionId}}` is a
   * probe mismatch / connect failure. Every `CompanyItem` carries the derived
   * `sourceKind` + (detail only) `documentPrerequisites` - LIVE since S2
   * (`modules/autocount/schemas.py CompanyItem`; the mock's "DB-only company
   * fixtures" block is the same contract, kept as the Vitest double).
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
   * per-field results. `rows` (optional) previews UNSAVED draft edits (now
   * scope-tagged, sprint-5/02). `lines` (sprint-5/02, AC-02-22) - a document
   * entity's fetched line records for the picked header (the caller fetches
   * them itself via `previewSqlQuery`/`useLineFetcher`, bound to the header's
   * `:doc_key` - the backend does the equivalent through
   * `SqlDbSource._read_lines`). Writes NOTHING - pure transform preview,
   * distinct from the slice-14 Sorento dry-run.
   */
  simulateMapping(
    companyId: string,
    entityType: string,
    record: Record<string, unknown>,
    rows?: AutocountMappingWriteRow[],
    lines?: Array<Record<string, unknown>>,
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
  /**
   * Run a candidate SELECT against the source, capped at 100 rows.
   *
   * `opts.bindDocKey` (plan 22 S5) - previewing a document's `lineQuery`
   * (which carries a `:doc_key` bound param): `true` binds `opts.docKey`
   * (a harmless sample, or `null`/omitted for a NULL bind - just enough to
   * let the query execute for column discovery). Omitted/`false` runs the
   * query exactly as before.
   */
  previewSqlQuery(
    connectionId: string,
    query: string,
    opts?: { bindDocKey?: boolean; docKey?: string | null },
  ): Promise<AutocountSqlPreview>;
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
  //        carries `nextIncrementalAt`/`nextReconcileAt` (read-only, recomputed
  //        by every PUT/activate/resume - `EtlService.next_run_times` computes
  //        + stores them server-side, `EtlTaskResponse` carries them on the
  //        wire). The schedule fields themselves (`incrementalMinutes`/
  //        `reconcileMode`/`reconcileHours`/`reconcileAt`) round-trip through
  //        the existing PUT + its 422 fieldErrors.
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

  // ── "Re-push all" (plan sprint-5/07, AC-07-13..24) ─────────────────────────
  //
  // BACKEND CONTRACT (S2b must match this EXACTLY - the mock is the spec):
  //
  //   POST /autocount/companies/{companyId}/entities/{entityType}/etl-task/repush
  //        → 200 AutocountEtlRepushResult {clearedCount, nextReconcileAt, status}
  //          - clears EVERY tracked row (`ac_row_hash`) for this (tenant,
  //          company, entityType) ONLY; `ac_doc_fingerprint`/the watermark are
  //          untouched. An `active` task gets `next_reconcile_at = now(utc)`
  //          (the next sweep claims a reconcile - `nextReconcileAt` echoes
  //          it); a `paused` task's stays `null` (nothing scheduled until
  //          resumed) - AC-07-14/15.
  //        → 409 (nothing deleted), body `{detail, message}` where `detail`
  //          is a PLAIN STRING for a draft task ("Activate the task first -
  //          a draft has nothing to re-push.") or a non-database task
  //          ("Re-push applies to database tasks only."), and the OBJECT
  //          `{message, runningRunId}` when a run for this (company, entity)
  //          is already in flight (AC-07-16) - the surface links to that run
  //          instead of the generic inline error.
  //        → 403 without `autocount.companies.manage`; 404 for another
  //          tenant's company (never resolved unscoped).
  //   Gated `autocount.companies.manage` (the same "configure the task"
  //   bucket as pause/activate/refetch-history - no new permission key).

  /**
   * Clear change tracking so the next reconcile re-pushes every document of
   * this (database) task. See the contract above.
   */
  repushEtlTask(companyId: string, entityType: string): Promise<AutocountEtlRepushResult>;

  // ── document mapping (sprint-5/02, S1 - AC-02-01..09/16..22) ───────────────
  //
  // BACKEND CONTRACT (S2/S3 backend must match this EXACTLY - the mock is the
  // spec). Additions to EXISTING routes first:
  //
  //   GET .../mapping  →  AutocountMappingView gains `lineSorentoFields` +
  //        `lineAcFields` (AC-02-02) - both empty for a master/GRN entity, so
  //        the Mapping tab renders a single section unchanged. Header
  //        `sorentoFields` gains the header fallback fields (AC-02-14).
  //
  //   PUT .../mapping  {rows}  →  AutocountMappingView - each row carries
  //        `scope: 'header' | 'line'` (default 'header', AC-02-01); a header
  //        re-map never deletes a line row and vice versa. Line rows are
  //        guarded exactly like header rows PLUS the ref-pairing +
  //        required-field rules (AC-02-03): `product_ref` only via
  //        `ref_product`, `warehouse_ref` only via `ref_warehouse`, and
  //        `source_ref`/`product_ref`/`qty_ordered` required the moment any
  //        line row is saved.
  //
  //   POST .../mapping/simulate  {record, rows, lines?}  →  AutocountSimulateResult
  //        gains `status` (AC-02-08/22) - the header's computed status AFTER
  //        the aggregates pass. `lines` (new, optional) - the picked header's
  //        fetched line records (the FE fetches them itself via
  //        `previewSqlQuery`/`useLineFetcher` bound to `:doc_key`, mirroring
  //        `SqlDbSource._read_lines` server-side); omitted = master/GRN
  //        behavior unchanged (`lineFields: []`).
  //
  //   GET .../mapping/functions  →  the formula catalog gains `startswith`,
  //        `coalesce` (AC-02-09) and the five `lines.*` aggregate variables
  //        for document entities (AC-02-07).
  //
  // New route:
  //
  //   GET /autocount/presets/{entityType}  →  AutocountMappingPreset | null
  //        (AC-02-16/17) - the AutoCount SQL-pack preset for one document
  //        entity, with `{database}` substituted for the company's
  //        `databaseName`. Null/absent for a non-document entity or one with
  //        no preset (foolproof-UI: "Use preset" is not offered then).
  //        Gated `autocount.companies.manage`.

  /** The AutoCount SQL-pack preset(s) for a document entity, database-substituted. */
  listMappingPresets(
    companyId: string,
    entityType: string,
  ): Promise<AutocountMappingPreset[]>;

  // ── open REST API source (sprint-5/08, S1 - AC-08-06/09/14/15) ─────────────
  //
  // Wire contract (kept as documentation post-S5; the backend now implements
  // this byte for byte - `modules/autocount/routers/{http,companies}.py`,
  // `.../schemas.py`).
  //
  //   GET /autocount/http/connections
  //        → AutocountApiConnection[] {id, name, baseUrl, auth}  - EVERY
  //          `autocount` connection of the tenant (both auths), tenant-scoped,
  //          gated `autocount.read` (AC-08-15). Feeds BOTH the connect-company
  //          picker (badging + the ref-prefix reveal, AC-08-09) and the task
  //          Source tab's connection picker (badging + impl derivation,
  //          AC-08-19) - ONE endpoint, not two.
  //
  //   POST /autocount/companies  {connectionId, name?, refPrefix?}
  //        → AutocountCompany - gains `refPrefix` (AC-08-06/07): REQUIRED
  //          (422 `{fieldErrors: {refPrefix}}`) when `connectionId` names an
  //          open (`auth: 'none'`) connection; trimmed, upper-cased,
  //          `^[A-Z0-9_]{2,32}$` server-side (`REF_PREFIX_RE` mirrors it
  //          client-side for the disabled-until-valid gate only - the 422 is
  //          still authoritative). Ignored (422 "not applicable") for a
  //          vendor/SQL connection. `AutocountCompany.sourceKind` gains
  //          `'http'` for an open company.
  //
  //   POST /autocount/http/preview  {connectionId, path, distinctOf?}
  //        → HttpPreview {envelope: 'paged'|'list', totalCount?, columns:
  //          [{name, sample}], rows (<=50), durationMs}  (AC-08-14). `paged`
  //          = a `{TotalCount,Page,PageSize,TotalPages,Data[]}` envelope
  //          (page 1, pageSize 50); `list` = a bare JSON array capped to 50.
  //          `distinctOf` set → rows are the distinct `{value}` projection,
  //          `columns == [{name:'value', sample:<first value>}]`. Errors map
  //          to 422 naming the step (`connectionId` for a non-open/foreign
  //          connection, `path` for a 404/non-JSON/timeout/`..`/query-string).
  //        Gated `autocount.manage` (same bucket as `/autocount/sql/preview`).
  //
  //   `AutocountEtlTask` (existing `/etl-task` routes) gains `sourceImpl`
  //        ('sql_db'|'autocount_http') and, when 'autocount_http', the task's
  //        `sourceConfig` carries `path`/`keyFields`/`watermarkField`/
  //        `comparedFields`/`distinctOf` ALONGSIDE the (unused, defaulted)
  //        SQL fields - ONE envelope, not a discriminated union on the wire,
  //        so Mapping/Schedule/Review & Activate/Runs keep reading the SAME
  //        `AutocountEtlTask.sourceConfig` shape unchanged (AC-08-19).
  //        CONFIRMED against the real backend (S5): `EtlSourceConfigIn`
  //        (`modules/autocount/schemas.py`) is that same flat envelope; the
  //        `sourceImpl` that picks which half of it is live is sent as a
  //        TOP-LEVEL sibling of `sourceConfig` on `PUT .../etl-task`
  //        (`EtlTaskUpdate.sourceImpl`, review round 1 B1 - it is NOT nested
  //        inside `sourceConfig` on the wire, only in this FE's local draft
  //        state).

  /** Every `autocount` connection of the tenant, badged by auth. */
  listApiConnections(): Promise<AutocountApiConnection[]>;
  /** Page-1 sample of an open-API endpoint path (<=50 rows), writes nothing. */
  previewHttp(input: HttpPreviewInput): Promise<HttpPreview>;
}

// ═══════════════════════════════════════════════════════════════════════════
// S5 (sprint-5/08) - swapped to the REAL service. The open REST API source
// (`listApiConnections`/`previewHttp`, the `refPrefix` company-create path,
// the `autocount_http` task fields documented above) is now backed by
// FastAPI end to end (S2 provider/company, S3 source/task, S4 brand, review
// round 1 fixes B1-B4/S1-S13). `mockAutocountService` stays as the frontend
// Vitest fixture only - import it directly in a test, never through this
// module.
// ═══════════════════════════════════════════════════════════════════════════
export const autocountService: AutocountService = realAutocountService;
