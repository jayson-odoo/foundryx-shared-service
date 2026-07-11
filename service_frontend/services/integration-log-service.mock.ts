/**
 * PHASE 1 MOCK — in-memory integration-log service (sprint-4/12).
 *
 * Used to build + tune the Developers → Logs console (loading / error / empty /
 * success states) BEFORE the real backend existed. The shipped boundary
 * (`integration-log-service.ts`) points at `.real`; this mock is retained only
 * for the frontend-first workflow + the service unit test. It is NOT wired into
 * the app.
 */
import { toCsv } from '@/lib/csv';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  IntegrationLogDetail,
  IntegrationLogItem,
  IntegrationLogStatus,
} from '@/types/integration-logs';
import type { IntegrationLogService } from './integration-log-service';

function _row(
  i: number,
  status: IntegrationLogStatus,
  operation: string,
  statusCode: number,
): IntegrationLogDetail {
  return {
    id: `log-${i}`,
    tenantId: 'tenant-demo',
    traceId: `trace-${i}`,
    source: 'inbound_api',
    workspaceId: 'ws-general',
    apiKeyId: 'key-abc',
    operation,
    method: operation.split(' ')[0],
    status,
    statusCode,
    errorCode: status === 'error' ? String(statusCode) : null,
    latencyMs: 20 + i * 3,
    externalRef: status === 'success' ? `wamid.${i}` : null,
    createdAt: new Date(Date.now() - i * 60_000).toISOString(),
    errorMessage: status === 'error' ? 'Invalid recipient number.' : null,
    requestSummary: {
      path: `/api/v1/omnichannel${operation.split(' ')[1] ?? ''}`,
      method: operation.split(' ')[0],
      headers: { authorization: '***', 'content-type': 'application/json' },
      query: {},
    },
    responseSummary: { statusCode },
  };
}

const MOCK_ROWS: IntegrationLogDetail[] = [
  _row(0, 'success', 'POST /messages', 200),
  _row(1, 'error', 'POST /messages', 422),
  _row(2, 'success', 'GET /contacts', 200),
  _row(3, 'error', 'POST /templates', 403),
  _row(4, 'success', 'GET /contacts/abc/messages', 200),
];

function _match(row: IntegrationLogItem, query: ListQuery): boolean {
  if (query.search) {
    const s = query.search.toLowerCase();
    const hay = `${row.operation} ${row.traceId ?? ''} ${row.externalRef ?? ''}`.toLowerCase();
    if (!hay.includes(s)) return false;
  }
  return true;
}

export const mockIntegrationLogService: IntegrationLogService = {
  async list(query: ListQuery): Promise<ListResult<IntegrationLogItem>> {
    const filtered = MOCK_ROWS.filter((r) => _match(r, query));
    const start = query.page * query.pageSize;
    return {
      data: filtered.slice(start, start + query.pageSize),
      total: filtered.length,
      page: query.page,
    };
  },

  async get(id: string): Promise<IntegrationLogDetail | null> {
    return MOCK_ROWS.find((r) => r.id === id) ?? null;
  },

  async export(query: ListQuery, columns: string[]): Promise<string> {
    const full = await this.list({ ...query, page: 0, pageSize: 200 });
    const rows = full.data.map((r) =>
      columns.map((c) => String((r as unknown as Record<string, unknown>)[c] ?? '')),
    );
    return toCsv(columns, rows);
  },
};
