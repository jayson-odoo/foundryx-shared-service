/**
 * Tenant admin service (plan 07) — the boundary the Platform Console talks to
 * (via hooks). Phase A binds the mock; Phase B swaps `tenantAdminService` to the
 * real api-client impl in ONE line (bottom of file). The interface IS the
 * backend contract (plan 07 §9).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { StatusGraph } from '@/types/status-engine';
import type {
  ProvisionTenantInput,
  TenantDetail,
  TenantListItem,
  UpdateTenantInput,
} from '@/types/tenant-admin';
import { realTenantAdminService } from './tenant-admin-service.real';

export interface TenantAdminService {
  list(query: ListQuery): Promise<ListResult<TenantListItem>>;
  get(id: string): Promise<TenantDetail>;
  /** Record-nav: the tenant at `index` within the ordered query, plus the total. */
  getAt(
    query: ListQuery,
    index: number,
  ): Promise<{ tenant: TenantDetail | null; total: number }>;
  /** Create tenant + seeded roles + first admin user — one transaction (plan 07 §7). */
  provision(input: ProvisionTenantInput): Promise<TenantDetail>;
  update(id: string, input: UpdateTenantInput): Promise<TenantDetail>;

  /** Lifecycle actions (plan 07 §4) — platform tenant rejected server-side. */
  suspend(id: string): Promise<TenantDetail>;
  reactivate(id: string): Promise<TenantDetail>;
  archive(id: string): Promise<TenantDetail>;
  /** Fire an explicit status-graph edge (sprint-2/01) — the generic move. */
  transition(id: string, transitionId: string): Promise<TenantDetail>;
  /** Hard delete (BL-035) — ARCHIVED tenants only; typed slug confirm. */
  purge(id: string, confirmSlug: string): Promise<void>;
  /** The tenant entity's status graph (tenants.read — decoupled from statuses.read). */
  statusGraph(): Promise<StatusGraph>;

  /** Selected rows if `ids` given, else the whole filtered set. Returns CSV text. */
  exportCsv(
    query: ListQuery,
    columns: string[],
    ids?: string[],
  ): Promise<string>;
}

// Phase B: real api-client. (Mock retained in tenant-admin-service.mock.ts.)
export const tenantAdminService: TenantAdminService = realTenantAdminService;
