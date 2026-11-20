import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args),
  };
});

import { realAutocountDocLookupService as svc } from './autocount-doc-lookup-service.real';

beforeEach(() => apiFetchMock.mockReset());

describe('realAutocountDocLookupService - wire paths', () => {
  it('lists types, optionally for a company', async () => {
    apiFetchMock.mockResolvedValue({ data: [] });
    await svc.listTypes();
    await svc.listTypes('c 1');
    expect(apiFetchMock.mock.calls.map((c) => c[0])).toEqual([
      '/autocount/doc-lookup/types',
      '/autocount/doc-lookup/types?companyId=c+1',
    ]);
  });

  it('reads stored sightings with the number url-encoded', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.stored('c1', 'PS2026/10 #4', 'delivery_order');
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/autocount/doc-lookup/stored?companyId=c1&docNo=PS2026%2F10+%234&docType=delivery_order',
    );
  });

  it('starts, polls and stops a job', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.start({ companyId: 'c1', docNo: 'X' });
    await svc.getJob('j/1');
    await svc.stop('j1');
    expect(apiFetchMock.mock.calls[0]).toEqual([
      '/autocount/doc-lookup',
      { method: 'POST', body: JSON.stringify({ companyId: 'c1', docNo: 'X' }) },
    ]);
    expect(apiFetchMock.mock.calls[1][0]).toBe('/autocount/doc-lookup/jobs/j%2F1');
    expect(apiFetchMock.mock.calls[2]).toEqual(['/autocount/doc-lookup/jobs/j1/stop', { method: 'POST' }]);
  });

  it('saves settings with PUT', async () => {
    apiFetchMock.mockResolvedValue({});
    await svc.saveSettings({ companyId: 'c1', lastModifiedBackDays: 3, docDateForwardDays: 5 });
    expect(apiFetchMock.mock.calls[0][1].method).toBe('PUT');
  });
});
