import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();

class MockApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

vi.mock('@/lib/api-client', () => ({
  apiFetch: (path: string, init?: RequestInit) => apiFetch(path, init),
  ApiError: MockApiError,
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

  it('reads staged records server-paginated (never an all-rows fetch)', async () => {
    apiFetch.mockResolvedValue({ job: {}, data: [], total: 0, noChangeCount: 0 });
    await realAutocountService.listStaged('job-1');
    expect(apiFetch).toHaveBeenCalledWith(
      '/autocount/jobs/job-1/staged?page=0&page_size=25',
      undefined,
    );
  });

  it('passes the changed filter, search and status params through', async () => {
    apiFetch.mockResolvedValue({ job: {}, data: [], total: 0, noChangeCount: 0 });
    await realAutocountService.listStaged('job-1', {
      page: 1,
      pageSize: 50,
      search: 'acme',
      changed: true,
      status: 'FAILED',
    });
    const url = apiFetch.mock.calls[0][0] as string;
    expect(url).toContain('page=1');
    expect(url).toContain('page_size=50');
    expect(url).toContain('search=acme');
    expect(url).toContain('changed=true');
    expect(url).toContain('status=FAILED');
  });

  it('re-fetches history by resetting an entity watermark (POST)', async () => {
    apiFetch.mockResolvedValue({ id: 'e1' });
    await realAutocountService.refetchHistory('c1', 'goods_received_note');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/autocount/companies/c1/entities/goods_received_note/refetch');
    expect(init.method).toBe('POST');
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

  it('POSTs the dry-run preview by job id', async () => {
    apiFetch.mockResolvedValue({ jobId: 'job-1', preview: { previewable: false } });
    await realAutocountService.preview('job-1');
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/autocount/jobs/job-1/preview');
    expect(init.method).toBe('POST');
  });

  it('PATCHes the sink target with the impl and connection', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realAutocountService.updateSinkTarget('c1', {
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-9',
    });
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe('/autocount/companies/c1/sink-target');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body as string)).toEqual({
      sinkImpl: 'sorento',
      sinkConnectionId: 'conn-9',
    });
  });

  it('clears the connection id when switching to the logging sink', async () => {
    apiFetch.mockResolvedValue({ id: 'c1' });
    await realAutocountService.updateSinkTarget('c1', { sinkImpl: 'logging' });
    expect(JSON.parse(apiFetch.mock.calls[0][1].body as string)).toEqual({
      sinkImpl: 'logging',
      sinkConnectionId: null,
    });
  });
});

describe('autocount mock service (frontend-first scaffolding)', () => {
  it('drives a previewable payload with a blanking overwrite and creates', async () => {
    const { mockAutocountService } = await import('./autocount-service.mock');
    const res = await mockAutocountService.preview('job-preview');
    expect(res.preview.previewable).toBe(true);
    if (!res.preview.previewable) throw new Error('expected previewable');
    expect(res.preview.summary.total).toBe(172);
    const overwrite = res.preview.predictions.find((p) => p.changesLiveData);
    expect(overwrite?.diff.payment_terms_days).toEqual({ current: 30, incoming: null });
    expect(res.preview.predictions.some((p) => p.outcome === 'created')).toBe(true);
  });

  it('drives the not-previewable (logging) state by job-id sentinel', async () => {
    const { mockAutocountService } = await import('./autocount-service.mock');
    const res = await mockAutocountService.preview('job-logging');
    expect(res.preview.previewable).toBe(false);
    if (res.preview.previewable) throw new Error('expected not previewable');
    expect(res.preview.reason).toMatch(/nothing to preview/i);
  });

  it('drives the dry-run failure state by job-id sentinel', async () => {
    const { mockAutocountService } = await import('./autocount-service.mock');
    await expect(mockAutocountService.preview('job-fail')).rejects.toMatchObject({
      status: 502,
    });
  });

  it('paginates staged records + reports the no-change count for the collapse', async () => {
    const { mockAutocountService } = await import('./autocount-service.mock');
    const changed = await mockAutocountService.listStaged('job-1', {
      page: 0,
      pageSize: 2,
      changed: true,
    });
    // Only records the operator must see, capped to the page size.
    expect(changed.data).toHaveLength(2);
    expect(changed.data.every((r) => r.hasChanges)).toBe(true);
    // The collapsed no-change count is constant regardless of page.
    expect(changed.noChangeCount).toBeGreaterThan(0);

    const noChange = await mockAutocountService.listStaged('job-1', { changed: false });
    expect(noChange.data.every((r) => !r.hasChanges)).toBe(true);
    expect(noChange.total).toBe(changed.noChangeCount);
  });

  it('re-fetch history resets the entity watermark (mock)', async () => {
    const { mockAutocountService } = await import('./autocount-service.mock');
    const res = await mockAutocountService.refetchHistory('c1', 'goods_received_note');
    expect(res.watermarkAt).toBeNull();
    expect(res.entityType).toBe('goods_received_note');
  });
});
