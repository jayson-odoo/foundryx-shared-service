/**
 * AutoCount ESB service (sprint-4/13, slice 1) — the boundary the
 * `/autocount/*` surfaces talk to via hooks. The interface IS the backend
 * contract: `modules/autocount/routers/{companies,sync}.py`.
 *
 * There is NO mock behind this boundary. The module's backend landed with this
 * slice, so the UI was built straight against it — a phase-1 mock here would be
 * debt with nothing to buy.
 *
 * Permission gates (module CSV, granted to tenant Admin by `AppStoreService`
 * on install): `autocount.companies.read/manage`, `autocount.sync.read/run`.
 */
import type {
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
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
  /** Trigger a manual sync (`POST /autocount/companies/{id}/sync`). */
  syncNow(companyId: string, entityType: string): Promise<AutocountSyncJob>;
  /** Run history for a company (`GET /autocount/companies/{id}/runs`). */
  listRuns(
    companyId: string,
    query?: AutocountListQuery & { entityType?: string },
  ): Promise<ListResult<AutocountSyncRun>>;
  /** Staged records + per-record diffs (`GET /autocount/jobs/{id}/staged`). */
  listStaged(jobId: string): Promise<AutocountStagedList>;
  /** Push the batch (`POST /autocount/jobs/{id}/approve`) — idempotent. */
  approve(jobId: string): Promise<AutocountApprovalResult>;
  /** Close without pushing (`POST /autocount/jobs/{id}/discard`). */
  discard(jobId: string): Promise<AutocountApprovalResult>;
}

export const autocountService: AutocountService = realAutocountService;
