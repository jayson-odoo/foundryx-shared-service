/**
 * Mock integration-log service (sprint-4/12) - the contract the Phase-B backend
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

  // AC-DLC-17: ordered legs of one consumption.
  it('getTrace returns the correlated legs oldest→newest', async () => {
    const trace = await svc.getTrace('trace-0');
    expect(trace).not.toBeNull();
    expect(trace!.traceId).toBe('trace-0');
    // The inbound leg + the outbound-Meta + webhook legs share trace-0.
    const sources = trace!.legs.map((l) => l.source);
    expect(sources).toContain('inbound_api');
    expect(sources).toContain('outbound_meta');
    expect(sources).toContain('webhook_delivery');
    // Ordered by created time.
    const times = trace!.legs.map((l) => l.createdAt);
    expect([...times].sort()).toEqual(times);
  });

  it('getTrace returns empty legs for an unknown trace', async () => {
    const trace = await svc.getTrace('trace-nope');
    expect(trace!.legs).toEqual([]);
  });

  // AC-DLC-21/23: retention settings round-trip.
  it('getSettings returns the deployment default', async () => {
    const s = await svc.getSettings();
    expect(s.retentionDays).toBe(30);
    expect(s.isDefault).toBe(true);
  });

  it('updateSettings persists an override (isDefault=false)', async () => {
    const updated = await svc.updateSettings(14);
    expect(updated).toEqual({ retentionDays: 14, isDefault: false });
    const again = await svc.getSettings();
    expect(again.retentionDays).toBe(14);
    expect(again.isDefault).toBe(false);
  });
});
