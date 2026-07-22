/**
 * AutoCount ESB service (sprint-4/13, slice 1) — the boundary the
 * `/autocount/*` surfaces talk to via hooks. The interface IS the backend
 * contract: `modules/autocount/routers/{companies,sync}.py`.
 *
 * The shipped binding is `.real` — the backend is live. A `.mock` sibling
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
  AutocountPreviewResult,
  AutocountSinkTargetInput,
  AutocountStagedList,
  AutocountSyncJob,
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
   * name back — there is deliberately no company field to supply.
   */
  createCompany(input: AutocountCompanyCreateInput): Promise<AutocountCompany>;
  /**
   * Adjust one entity's sync configuration
   * (`PATCH /autocount/companies/{id}/entities/{entityType}`). Narrow by
   * design — the initial lookback window only, and changing it re-fetches
   * nothing.
   */
  updateEntityConfig(
    companyId: string,
    entityType: string,
    input: AutocountEntityConfigUpdate,
  ): Promise<AutocountEntityConfig>;
  /** Trigger a manual sync (`POST /autocount/companies/{id}/sync`). */
  syncNow(companyId: string, entityType: string): Promise<AutocountSyncJob>;
  /** Run history for a company (`GET /autocount/companies/{id}/runs`). */
  listRuns(
    companyId: string,
    query?: AutocountListQuery & { entityType?: string },
  ): Promise<ListResult<AutocountSyncRun>>;
  /** Staged records + per-record diffs (`GET /autocount/jobs/{id}/staged`). */
  listStaged(jobId: string): Promise<AutocountStagedList>;
  /**
   * Dry-run the batch against the consumer, writing nothing
   * (`POST /autocount/jobs/{id}/preview`). Returns the consumer's own
   * prediction — the overwrite gate (AC-14-20/21). A logging-sink company
   * yields a "not previewable" shape; an unreachable consumer throws (HTTP 502).
   */
  preview(jobId: string): Promise<AutocountPreviewResult>;
  /** Push the batch (`POST /autocount/jobs/{id}/approve`) — idempotent. */
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
}

export const autocountService: AutocountService = realAutocountService;
