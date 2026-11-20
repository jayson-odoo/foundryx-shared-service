/**
 * Plan 63 (AC-63-34..36, RED): the calls methods on the autocount service trio. Mocked at the
 * api-client boundary: only the URL (path + query) the real service builds is asserted.
 */
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

const { realAutocountService } = await import('./autocount-service.real');
const { mockAutocountService } = await import('./autocount-service.mock');
const { autocountService } = await import('./autocount-service');

interface CallsApi {
  listCalls: (query?: Record<string, unknown>) => Promise<{ data: unknown[]; total: number; page: number }>;
  getCallFilterOptions: () => Promise<{ books: string[]; docTypes: string[]; outcomes: string[]; persons: { id: string; name: string }[] }>;
  getCall: (id: string) => Promise<Record<string, unknown>>;
}

function calls(service: unknown): CallsApi {
  const api = service as Partial<CallsApi>;
  for (const name of ['listCalls', 'getCallFilterOptions', 'getCall'] as const) {
    if (typeof api[name] !== 'function') throw new Error(`autocount service has no ${name}`);
  }
  return api as CallsApi;
}

function lastUrl(): URL {
  const path = apiFetch.mock.calls[apiFetch.mock.calls.length - 1][0] as string;
  return new URL(path, 'http://backend.test');
}

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockResolvedValue({ data: [], total: 0, page: 0 });
});

describe('listCalls (AC-63-31, 32)', () => {
  it('hits the calls collection and returns the page untouched', async () => {
    const page = { data: [{ id: 'c1' }], total: 1, page: 0 };
    apiFetch.mockResolvedValueOnce(page);
    await expect(calls(realAutocountService).listCalls({})).resolves.toEqual(page);
    expect(lastUrl().pathname).toMatch(/\/autocount\/calls$/);
  });

  it('maps every filter, the sort and the paging to the planned query parameters', async () => {
    await calls(realAutocountService).listCalls({
      page: 1,
      pageSize: 50,
      sort: 'durationMs',
      order: 'desc',
      dateFrom: '2026-11-01T00:00:00Z',
      dateTo: '2026-11-03T23:59:59Z',
      companyId: ['co-1', 'co-2'],
      book: ['db3', 'db1'],
      docType: ['SO'],
      outcome: ['ok', 'timeout'],
      person: ['u1'],
      search: 'so 100',
    });
    const q = lastUrl().searchParams;
    expect(q.get('page')).toBe('1');
    expect(q.get('pageSize')).toBe('50');
    expect(q.get('sort')).toBe('durationMs');
    expect(q.get('order')).toBe('desc');
    expect(q.get('dateFrom')).toBe('2026-11-01T00:00:00Z');
    expect(q.get('dateTo')).toBe('2026-11-03T23:59:59Z');
    expect(q.getAll('companyId')).toEqual(['co-1', 'co-2']);
    expect(q.getAll('book')).toEqual(['db3', 'db1']);
    expect(q.getAll('docType')).toEqual(['SO']);
    expect(q.getAll('outcome')).toEqual(['ok', 'timeout']);
    expect(q.getAll('person')).toEqual(['u1']);
    expect(q.get('search')).toBe('so 100');
  });

  it('omits empty filters and never sends the text "undefined"', async () => {
    await calls(realAutocountService).listCalls({ book: [], outcome: undefined, search: '', person: [] });
    const q = lastUrl().searchParams;
    for (const key of ['book', 'outcome', 'search', 'person', 'sort', 'order', 'dateFrom', 'dateTo', 'companyId', 'docType']) {
      expect(q.has(key)).toBe(false);
    }
    expect(lastUrl().search).not.toMatch(/undefined|null/);
  });

  it('never sends a tenant id (the tenant comes from the token)', async () => {
    await calls(realAutocountService).listCalls({ book: ['db3'] });
    expect(lastUrl().search.toLowerCase()).not.toContain('tenant');
  });
});

describe('getCallFilterOptions and getCall (AC-63-33, 36)', () => {
  it('reads the filter options from the calls/filter-options path', async () => {
    const options = { books: ['db3'], docTypes: ['SO'], outcomes: ['ok'], persons: [{ id: 'u1', name: 'Una' }] };
    apiFetch.mockResolvedValueOnce(options);
    await expect(calls(realAutocountService).getCallFilterOptions()).resolves.toEqual(options);
    expect(lastUrl().pathname).toMatch(/\/autocount\/calls\/filter-options$/);
  });

  it('reads one call by id, url-encoding the id', async () => {
    const detail = { id: 'call/1', requestJson: { a: 1 }, responseBody: 'ok' };
    apiFetch.mockResolvedValueOnce(detail);
    await expect(calls(realAutocountService).getCall('call/1')).resolves.toEqual(detail);
    expect(lastUrl().pathname).toMatch(/\/autocount\/calls\/call%2F1$/);
  });
});

describe('the service trio exposes the same three methods', () => {
  it('the mock resolves a page, options and a detail without the network', async () => {
    const mock = calls(mockAutocountService);
    const page = await mock.listCalls({ page: 0, pageSize: 25 });
    expect(Array.isArray(page.data)).toBe(true);
    expect(typeof page.total).toBe('number');
    const options = await mock.getCallFilterOptions();
    expect(Array.isArray(options.books) && Array.isArray(options.persons)).toBe(true);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it('the exported autocountService carries them (real-backed once swapped)', () => {
    calls(autocountService);
  });
});
