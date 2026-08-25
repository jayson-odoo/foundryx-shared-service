/** Real integration-log service - talks to FastAPI via the shared api-client
 * (`GET /integration-logs`, `GET /integration-logs/{id}`). */
import { apiFetch } from '@/lib/api-client';
import { toCsv } from '@/lib/csv';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  IntegrationLogDetail,
  IntegrationLogItem,
  IntegrationLogSettings,
  IntegrationLogTrace,
} from '@/types/integration-logs';
import type { IntegrationLogService } from './integration-log-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realIntegrationLogService: IntegrationLogService = {
  list(query: ListQuery): Promise<ListResult<IntegrationLogItem>> {
    return apiFetch<ListResult<IntegrationLogItem>>(
      `/integration-logs?${listParams(query).toString()}`,
    );
  },

  get(id: string): Promise<IntegrationLogDetail | null> {
    return apiFetch<IntegrationLogDetail>(`/integration-logs/${id}`).catch(() => null);
  },

  getTrace(traceId: string): Promise<IntegrationLogTrace | null> {
    return apiFetch<IntegrationLogTrace>(
      `/integration-logs/trace/${encodeURIComponent(traceId)}`,
    ).catch(() => null);
  },

  async export(query: ListQuery, columns: string[]): Promise<string> {
    const full = await this.list({ ...query, page: 0, pageSize: 200 });
    const rows = full.data.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return toCsv(columns, rows);
  },

  getSettings(): Promise<IntegrationLogSettings> {
    return apiFetch<IntegrationLogSettings>('/integration-logs/settings');
  },

  updateSettings(retentionDays: number): Promise<IntegrationLogSettings> {
    return apiFetch<IntegrationLogSettings>('/integration-logs/settings', {
      method: 'PUT',
      body: JSON.stringify({ retentionDays }),
    });
  },
};
