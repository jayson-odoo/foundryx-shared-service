/**
 * Real tenant admin service (Phase B) — talks to FastAPI via the shared
 * api-client. Backend returns camelCase matching the tenant-admin types, so no
 * field remapping. Bound in one line from tenant-admin-service.ts when the
 * backend lands (plan 07 §9 endpoints, all require_platform_permission).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { StatusGraph } from '@/types/status-engine';
import type {
  ProvisionTenantInput,
  TenantDetail,
  TenantListItem,
  UpdateTenantInput,
} from '@/types/tenant-admin';
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type { TenantAdminService } from './tenant-admin-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.statusView) p.set('status_view', query.statusView);
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

function navParams(query: ListQuery, index: number): URLSearchParams {
  const p = new URLSearchParams();
  p.set('index', String(index));
  if (query.statusView) p.set('status_view', query.statusView);
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realTenantAdminService: TenantAdminService = {
  list(query) {
    return apiFetch<ListResult<TenantListItem>>(
      `/platform/tenants?${listParams(query).toString()}`,
    );
  },
  get(id) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}`);
  },
  getAt(query, index) {
    return apiFetch<{ tenant: TenantDetail | null; total: number }>(
      `/platform/tenants/at?${navParams(query, index).toString()}`,
    );
  },
  provision(input: ProvisionTenantInput) {
    return apiFetch<TenantDetail>('/platform/tenants', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  update(id, input: UpdateTenantInput) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  suspend(id) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}/suspend`, {
      method: 'POST',
    });
  },
  reactivate(id) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}/reactivate`, {
      method: 'POST',
    });
  },
  archive(id) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}/archive`, {
      method: 'POST',
    });
  },
  transition(id, transitionId) {
    return apiFetch<TenantDetail>(`/platform/tenants/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ transitionId }),
    });
  },
  async purge(id, confirmSlug) {
    await apiFetch<void>(`/platform/tenants/${id}/purge`, {
      method: 'POST',
      body: JSON.stringify({ confirmSlug }),
    });
  },
  statusGraph() {
    return apiFetch<StatusGraph>('/platform/tenants/status-graph');
  },
  exportCsv(query, columns, ids) {
    return apiFetchText('/platform/tenants/export', {
      method: 'POST',
      body: JSON.stringify({
        columns,
        ids,
        statusView: query.statusView ?? 'active',
        search: query.search,
        sortBy: query.sort?.id,
        sortDir: query.sort ? (query.sort.desc ? 'desc' : 'asc') : undefined,
        filter: query.filter,
      }),
    });
  },
};
