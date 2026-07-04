/**
 * Real integration service — talks to FastAPI via the shared api-client.
 * Endpoints follow plan 09 §6 + the plan 06 Resource-shell additions
 * (list/at/export). Bound in Phase B.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  Connection,
  ConnectionInput,
  IntegrationProvider,
  TestConnectionResult,
} from '@/types/integration';
import type { ListQuery } from '@/types/resource';
import type { IntegrationService } from './integration-service';

function queryParams(query: ListQuery, index?: number): URLSearchParams {
  const p = new URLSearchParams();
  if (index === undefined) {
    p.set('page', String(query.page));
    p.set('page_size', String(query.pageSize));
  } else {
    p.set('index', String(index));
  }
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realIntegrationService: IntegrationService = {
  providers() {
    return apiFetch<IntegrationProvider[]>('/integrations/providers');
  },
  list(query) {
    return apiFetch(`/integrations/connections?${queryParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<Connection>(`/integrations/connections/${id}`);
  },
  getAt(query, index) {
    return apiFetch(`/integrations/connections/at?${queryParams(query, index).toString()}`);
  },
  exportCsv(query, columns, ids) {
    const p = queryParams(query);
    p.set('columns', columns.join(','));
    if (ids?.length) p.set('ids', ids.join(','));
    return apiFetchText(`/integrations/connections/export?${p.toString()}`);
  },
  create(input: ConnectionInput) {
    return apiFetch<Connection>('/integrations/connections', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  update(id, input) {
    return apiFetch<Connection>(`/integrations/connections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async remove(id) {
    await apiFetch<void>(`/integrations/connections/${id}`, { method: 'DELETE' });
  },
  test(id, target) {
    return apiFetch<TestConnectionResult>(`/integrations/connections/${id}/test`, {
      method: 'POST',
      body: JSON.stringify(target ? { target } : {}),
    });
  },
};
