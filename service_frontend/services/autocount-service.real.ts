/**
 * Real AutoCount service — talks to FastAPI via the shared api-client. Router
 * prefixes come from the module manifest: companies at `/autocount/companies`,
 * sync at `/autocount`.
 */
import { apiFetch } from '@/lib/api-client';
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
import type { AutocountListQuery, AutocountService } from './autocount-service';

function pageParams(query: AutocountListQuery = {}): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page ?? 0));
  // The backend caps page_size at 200 — asking for more is a 422, not a bigger
  // page, so never send an uncapped "give me everything" size.
  p.set('page_size', String(Math.min(query.pageSize ?? 25, 200)));
  return p;
}

export const realAutocountService: AutocountService = {
  listCompanies(query = {}) {
    return apiFetch<ListResult<AutocountCompany>>(
      `/autocount/companies?${pageParams(query).toString()}`,
    );
  },

  getCompany(id) {
    return apiFetch<AutocountCompanyDetail>(`/autocount/companies/${id}`);
  },

  createCompany(input: AutocountCompanyCreateInput) {
    return apiFetch<AutocountCompany>('/autocount/companies', {
      method: 'POST',
      body: JSON.stringify({ connectionId: input.connectionId, name: input.name ?? '' }),
    });
  },

  syncNow(companyId, entityType) {
    return apiFetch<AutocountSyncJob>(`/autocount/companies/${companyId}/sync`, {
      method: 'POST',
      body: JSON.stringify({ entityType }),
    });
  },

  listRuns(companyId, query = {}) {
    const p = pageParams(query);
    if (query.entityType) p.set('entity_type', query.entityType);
    return apiFetch<ListResult<AutocountSyncRun>>(
      `/autocount/companies/${companyId}/runs?${p.toString()}`,
    );
  },

  listStaged(jobId) {
    return apiFetch<AutocountStagedList>(`/autocount/jobs/${jobId}/staged`);
  },

  approve(jobId) {
    return apiFetch<AutocountApprovalResult>(`/autocount/jobs/${jobId}/approve`, {
      method: 'POST',
    });
  },

  discard(jobId) {
    return apiFetch<AutocountApprovalResult>(`/autocount/jobs/${jobId}/discard`, {
      method: 'POST',
    });
  },
};
