import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();

vi.mock('@/lib/api-client', () => ({
  apiFetch: (path: string, init?: RequestInit) => apiFetch(path, init),
}));

// Imported after the mock so the real api-client is never reached.
const { realAutocountService } = await import('./autocount-service.real');

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockResolvedValue({ data: [], total: 0, page: 0 });
});

describe('autocount service (real boundary)', () => {
  it('lists companies page-based', async () => {
    await realAutocountService.listCompanies({ page: 2, pageSize: 50 });
    expect(apiFetch).toHaveBeenCalledWith(
      '/autocount/companies?page=2&page_size=50',
      undefined,
    );
  });

  it('defaults paging when none is supplied', async () => {
    await realAutocountService.listCompanies();
    expect(apiFetch.mock.calls[0][0]).toBe('/autocount/companies?page=0&page_size=25');
  });

  it('caps page_size at the endpoint maximum (a bigger ask is a 422, not a bigger page)', async () => {
    await realAutocountService.listCompanies({ pageSize: 500 });
    expect(apiFetch.mock.calls[0][0]).toContain('page_size=200');
  });

  it('creates a company from a connection ONLY — never a typed company name', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realAutocountService.createCompany({ connectionId: 'conn-1', name: 'Main' });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/autocount/companies');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ connectionId: 'conn-1', name: 'Main' });
    expect(body).not.toHaveProperty('databaseName');
    expect(body).not.toHaveProperty('companyName');
  });

  it('sends a blank label when none is given', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realAutocountService.createCompany({ connectionId: 'conn-1' });
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string).name).toBe('');
  });

  it('triggers a manual sync for one entity', async () => {
    apiFetch.mockResolvedValue({ id: 'job-1', status: 'needs_review' });
    await realAutocountService.syncNow('c1', 'goods_received_note');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/autocount/companies/c1/sync');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      entityType: 'goods_received_note',
    });
  });

  it('lists runs, optionally narrowed to one entity', async () => {
    await realAutocountService.listRuns('c1', { entityType: 'goods_received_note' });
    expect(apiFetch.mock.calls[0][0]).toBe(
      '/autocount/companies/c1/runs?page=0&page_size=25&entity_type=goods_received_note',
    );
  });

  it('reads staged records for a job', async () => {
    apiFetch.mockResolvedValue({ job: {}, data: [], total: 0 });
    await realAutocountService.listStaged('job-1');
    expect(apiFetch).toHaveBeenCalledWith('/autocount/jobs/job-1/staged', undefined);
  });

  it('approves and discards by job id', async () => {
    apiFetch.mockResolvedValue({ jobId: 'job-1', result: {} });
    await realAutocountService.approve('job-1');
    expect(apiFetch.mock.calls[0][0]).toBe('/autocount/jobs/job-1/approve');
    expect(apiFetch.mock.calls[0][1].method).toBe('POST');

    await realAutocountService.discard('job-1');
    expect(apiFetch.mock.calls[1][0]).toBe('/autocount/jobs/job-1/discard');
    expect(apiFetch.mock.calls[1][1].method).toBe('POST');
  });
});
