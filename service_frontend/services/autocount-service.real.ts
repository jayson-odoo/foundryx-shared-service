/**
 * Real AutoCount service - talks to FastAPI via the shared api-client. Router
 * prefixes come from the module manifest: companies at `/autocount/companies`,
 * sync at `/autocount`.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  AutocountApprovalResult,
  AutocountCompany,
  AutocountCompanyCreateInput,
  AutocountCompanyDetail,
  AutocountEntityConfig,
  AutocountFormulaTestResult,
  AutocountJobListQuery,
  AutocountMappingUpdate,
  AutocountMappingView,
  AutocountMappingWriteRow,
  AutocountPreviewResult,
  AutocountSimulateResult,
  AutocountStagedList,
  AutocountSyncJob,
  AutocountSyncJobBatch,
  AutocountSyncRun,
} from '@/types/autocount';
import type { ListResult } from '@/types/resource';
import type { AutocountStagedQuery } from '@/types/autocount';
import type { AutocountListQuery, AutocountService } from './autocount-service';

function pageParams(query: AutocountListQuery = {}): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page ?? 0));
  // The backend caps page_size at 200 - asking for more is a 422, not a bigger
  // page, so never send an uncapped "give me everything" size.
  p.set('page_size', String(Math.min(query.pageSize ?? 25, 200)));
  return p;
}

function stagedParams(query: AutocountStagedQuery = {}): URLSearchParams {
  const p = pageParams(query);
  if (query.search) p.set('search', query.search);
  if (query.changed !== undefined) p.set('changed', String(query.changed));
  if (query.status) p.set('status', query.status);
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

  updateEntityConfig(companyId, entityType, input) {
    return apiFetch<AutocountEntityConfig>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    );
  },

  syncNow(companyId, entityType) {
    return apiFetch<AutocountSyncJob>(`/autocount/companies/${companyId}/sync`, {
      method: 'POST',
      body: JSON.stringify({ entityType }),
    });
  },

  refetchHistory(companyId, entityType) {
    // BACKEND NEEDED: endpoint not yet implemented (flagged in the interface).
    return apiFetch<AutocountEntityConfig>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/refetch`,
      { method: 'POST' },
    );
  },

  listJobs(query: AutocountJobListQuery = {}) {
    const p = pageParams(query);
    // Default segment = the batches awaiting attention; `all` widens it.
    p.set('status', query.status ?? 'needs_review');
    if (query.entityType) p.set('entityType', query.entityType);
    return apiFetch<ListResult<AutocountSyncJobBatch>>(
      `/autocount/jobs?${p.toString()}`,
    );
  },

  listRuns(companyId, query = {}) {
    const p = pageParams(query);
    if (query.entityType) p.set('entity_type', query.entityType);
    return apiFetch<ListResult<AutocountSyncRun>>(
      `/autocount/companies/${companyId}/runs?${p.toString()}`,
    );
  },

  listStaged(jobId, query = {}) {
    return apiFetch<AutocountStagedList>(
      `/autocount/jobs/${jobId}/staged?${stagedParams(query).toString()}`,
    );
  },

  preview(jobId) {
    return apiFetch<AutocountPreviewResult>(`/autocount/jobs/${jobId}/preview`, {
      method: 'POST',
    });
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

  updateSinkTarget(companyId, input) {
    return apiFetch<AutocountCompany>(
      `/autocount/companies/${companyId}/sink-target`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          sinkImpl: input.sinkImpl,
          sinkConnectionId: input.sinkConnectionId ?? null,
        }),
      },
    );
  },

  getMapping(companyId, entityType) {
    return apiFetch<AutocountMappingView>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping`,
    );
  },

  updateMapping(companyId, entityType, input: AutocountMappingUpdate) {
    return apiFetch<AutocountMappingView>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping`,
      {
        method: 'PUT',
        body: JSON.stringify({ rows: input.rows.map(writeRow) }),
      },
    );
  },

  testFormula(companyId, entityType, formula, value) {
    return apiFetch<AutocountFormulaTestResult>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping/test-formula`,
      { method: 'POST', body: JSON.stringify({ formula, value }) },
    );
  },

  simulateMapping(companyId, entityType, record, rows) {
    const body: { record: Record<string, unknown>; rows?: ReturnType<typeof writeRow>[] } = {
      record,
    };
    // Only send `rows` when previewing DRAFT edits; omit to simulate saved rows.
    if (rows) body.rows = rows.map(writeRow);
    return apiFetch<AutocountSimulateResult>(
      `/autocount/companies/${companyId}/entities/${encodeURIComponent(entityType)}/mapping/simulate`,
      { method: 'POST', body: JSON.stringify(body) },
    );
  },
};

/** The wire shape of one mapping row on write (a blank formula → null). */
function writeRow(row: AutocountMappingWriteRow) {
  const formula = row.formula?.trim();
  return {
    sourcePath: row.sourcePath,
    transform: row.transform,
    sorentoField: row.sorentoField,
    formula: formula ? formula : null,
  };
}
