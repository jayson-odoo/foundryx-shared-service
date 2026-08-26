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
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateResult,
  AutocountSinkTargetInput,
  AutocountStagedList,
  AutocountStagedQuery,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
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
}

export const autocountService: AutocountService = realAutocountService;
