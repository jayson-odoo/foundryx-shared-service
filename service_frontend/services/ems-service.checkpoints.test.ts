import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchText = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiFetchText: (...a: unknown[]) => apiFetchText(...a),
}));

import { emsService } from './ems-service';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('emsService check-in (Cluster D slice 3)', () => {
  it('listCheckpoints GETs the project checkpoints', async () => {
    apiFetch.mockResolvedValue([]);
    await emsService.listCheckpoints('p1');
    const [path] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/checkpoints');
  });

  it('createCheckpoint POSTs name + segment', async () => {
    apiFetch.mockResolvedValue({ id: 'c1', name: 'Gate', entryType: 'single' });
    await emsService.createCheckpoint('p1', { name: 'Gate', segmentId: 's1' });
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/checkpoints');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ name: 'Gate', segmentId: 's1' });
  });

  it('scanTicket POSTs the qrToken to the scan endpoint', async () => {
    apiFetch.mockResolvedValue({ result: 'admitted', reason: null, ticketId: 'tk1' });
    const res = await emsService.scanTicket('p1', 'c1', 'tok-abc');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/checkpoints/c1/scan');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse((opts as { body: string }).body)).toEqual({ qrToken: 'tok-abc' });
    expect(res.result).toBe('admitted');
  });

  it('listCheckpointLogs GETs the logs endpoint with a page_size', async () => {
    apiFetch.mockResolvedValue({ items: [], total: 0, page: 0, pageSize: 25 });
    await emsService.listCheckpointLogs('p1', 'c1');
    const [path] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/checkpoints/c1/logs?page_size=25');
  });
});
