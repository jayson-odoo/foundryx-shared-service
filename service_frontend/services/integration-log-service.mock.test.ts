/**
 * Mock integration-log service (sprint-4/12) — the contract the Phase-B backend
 * mirrors: paginated list, search over operation/trace/external-ref, redacted
 * payloads, single-row detail, CSV export.
 */
import { describe, expect, it } from 'vitest';
import type { ListQuery } from '@/types/resource';
import { mockIntegrationLogService as svc } from './integration-log-service.mock';

const query = (over: Partial<ListQuery> = {}): ListQuery => ({
  page: 0,
  pageSize: 50,
  ...over,
});

describe('mock integration-log service', () => {
  it('lists all rows with a total', async () => {
    const res = await svc.list(query());
    expect(res.total).toBeGreaterThan(0);
    expect(res.data.length).toBe(res.total);
    expect(res.data[0].source).toBe('inbound_api');
  });

  it('paginates', async () => {
    const first = await svc.list(query({ pageSize: 2, page: 0 }));
    const second = await svc.list(query({ pageSize: 2, page: 1 }));
    expect(first.data.length).toBe(2);
    expect(first.data[0].id).not.toBe(second.data[0]?.id);
  });

  it('searches operation / trace / external ref', async () => {
    const res = await svc.list(query({ search: 'templates' }));
    expect(res.data.length).toBeGreaterThan(0);
    expect(res.data.every((r) => r.operation.toLowerCase().includes('templates'))).toBe(true);
  });

  it('detail carries redacted request headers (no plaintext key)', async () => {
    const { data } = await svc.list(query());
    const detail = await svc.get(data[0].id);
    expect(detail).not.toBeNull();
    const headers = (detail!.requestSummary as { headers: Record<string, string> }).headers;
    expect(headers.authorization).toBe('***');
    expect(JSON.stringify(detail!.requestSummary)).not.toContain('fxw_live');
  });

  it('get returns null for an unknown id', async () => {
    expect(await svc.get('nope')).toBeNull();
  });

  it('exports CSV with a header row', async () => {
    const csv = await svc.export(query(), ['source', 'operation', 'status']);
    const lines = csv.trim().split('\n');
    expect(lines[0]).toContain('source');
    expect(lines.length).toBeGreaterThan(1);
  });
});
