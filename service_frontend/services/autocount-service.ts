/**
 * AutoCount ESB service (sprint-4/13, slice 1) - the boundary the
 * `/autocount/*` surfaces talk to via hooks. The interface IS the backend
 * contract: `modules/autocount/routers/{companies,sync}.py`.
 *
 * The shipped binding is `.real` - the backend is live. A `.mock` sibling
 * exists ONLY as frontend-first scaffolding for the dry-run review states
 * (previewable / not-previewable / failure) and the Vitest suite; flip the
 * export at the bottom to `mockAutocountService` to build against it, back to
 * `.real` to ship (the house service-trio pattern).
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
import { mockAutocountService } from './autocount-service.mock';
import { realAutocountService } from './autocount-service.real';

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
   * design - the initial lookback window only, and changing it re-fetches
   * nothing.
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
   * target; `sorento` requires a `sinkConnectionId`.
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
}

/**
 * PHASE 1 MOCK (plan 22 S1): the five direct-DB ETL methods bind the MOCK -
 * the backend endpoints do not exist yet. Everything else stays real. Phase 2
 * swaps this composite back to a bare `realAutocountService`.
 */
export const autocountService: AutocountService = {
  ...realAutocountService,
  listSqlConnections: mockAutocountService.listSqlConnections,
  getSqlSchema: mockAutocountService.getSqlSchema,
  previewSqlQuery: mockAutocountService.previewSqlQuery,
  getEtlTask: mockAutocountService.getEtlTask,
  updateEtlTask: mockAutocountService.updateEtlTask,
};
