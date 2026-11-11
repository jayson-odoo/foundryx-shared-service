/**
 * Plan 63 round 1 (AC-63-34, RED): the Time filter is range-only, a half-open range maps to one
 * instant bound, and the list query round-trips through the address bar (restored once on load).
 */
import { act, render, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSearchParams } from 'next/navigation';
import { ResourceList } from '@/components/platform/resource-list';
import { encodeListQuery } from '@/lib/list-context';
import type { FilterGroup, ListQuery } from '@/types/resource';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/calls'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: ['autocount.sync.read'], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({ useImportActivity: () => ({ openImport: vi.fn() }) }));

const listCalls = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    listCalls: (...a: unknown[]) => listCalls(...a),
    getCallFilterOptions: vi.fn().mockResolvedValue({ books: [], docTypes: [], outcomes: [], persons: [] }),
    getCall: vi.fn(),
    listCompanies: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }),
  },
}));

const { useCallsListConfig } = await import('./use-calls-list-config');

function range(value: string[]): FilterGroup {
  return { kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'createdAt', operator: 'between', value }] };
}

beforeEach(() => {
  vi.clearAllMocks();
  listCalls.mockResolvedValue({ data: [], total: 0, page: 0 });
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
  window.history.replaceState(null, '', '/autocount/calls');
});

describe('Time filter field (AC-63-34)', () => {
  it('is a date field restricted to the range operator', () => {
    const { result } = renderHook(() => useCallsListConfig());
    const field = result.current.filterFields.find((f) => f.field === 'createdAt') as
      | (typeof result.current.filterFields)[number] & { operators?: string[] }
      | undefined;
    expect(field?.type).toBe('date');
    expect(field?.operators).toEqual(['between']);
  });
});

describe('readRange through the fetcher (AC-63-31, 34)', () => {
  async function fetchWith(value: string[]) {
    const { result } = renderHook(() => useCallsListConfig());
    await act(async () => {
      await result.current.fetcher({ page: 0, pageSize: 25, filter: range(value) });
    });
    return listCalls.mock.calls[0][0] as { dateFrom?: string; dateTo?: string };
  }

  it('a full day range is the Malaysian day start to the last millisecond of the end day, as UTC', async () => {
    const q = await fetchWith(['2026-11-05', '2026-11-06']);
    expect(q.dateFrom).toBe('2026-11-04T16:00:00.000Z');
    expect(q.dateTo).toBe('2026-11-06T15:59:59.999Z');
  });

  it('a start only keeps the start and sends no end', async () => {
    const q = await fetchWith(['2026-11-05', '']);
    expect(q.dateFrom).toBe('2026-11-04T16:00:00.000Z');
    expect(q.dateTo).toBeUndefined();
  });

  it('an end only keeps the end and sends no start', async () => {
    const q = await fetchWith(['', '2026-11-06']);
    expect(q.dateTo).toBe('2026-11-06T15:59:59.999Z');
    expect(q.dateFrom).toBeUndefined();
  });

  it('no time filter sends no bounds', async () => {
    const { result } = renderHook(() => useCallsListConfig());
    await act(async () => {
      await result.current.fetcher({ page: 0, pageSize: 25 });
    });
    const q = listCalls.mock.calls[0][0] as { dateFrom?: string; dateTo?: string };
    expect(q.dateFrom).toBeUndefined();
    expect(q.dateTo).toBeUndefined();
  });
});

function Harness() {
  const config = useCallsListConfig();
  return <ResourceList config={config} />;
}

describe('urlState round trip (AC-63-34)', () => {
  it('opts into urlState', () => {
    const { result } = renderHook(() => useCallsListConfig());
    expect(result.current.urlState).toBe(true);
  });

  it('restores page, sort, search and filters from ctx on the first load', async () => {
    const saved: ListQuery = {
      page: 1,
      pageSize: 25,
      search: 'so-1',
      sort: { id: 'durationMs', desc: true },
      filter: {
        kind: 'group',
        combinator: 'and',
        rules: [
          { kind: 'condition', field: 'book', operator: 'in', value: ['db3'] },
          { kind: 'condition', field: 'createdAt', operator: 'between', value: ['2026-11-05', '2026-11-06'] },
        ],
      },
    };
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ ctx: encodeListQuery(saved) }) as unknown as ReturnType<typeof useSearchParams>,
    );
    render(<Harness />);
    await waitFor(() => expect(listCalls).toHaveBeenCalled());
    const first = listCalls.mock.calls[0][0] as Record<string, unknown>;
    expect(first).toMatchObject({
      page: 1, search: 'so-1', sort: 'durationMs', order: 'desc', book: ['db3'],
      dateFrom: '2026-11-04T16:00:00.000Z', dateTo: '2026-11-06T15:59:59.999Z',
    });
  });

  it('writes the live query back into the address bar', async () => {
    render(<Harness />);
    await waitFor(() => expect(listCalls).toHaveBeenCalled());
    await waitFor(() => expect(new URL(window.location.href).searchParams.get('ctx')).toBeTruthy());
  });

  it('control: without ctx the first fetch is the default newest-first page', async () => {
    render(<Harness />);
    await waitFor(() => expect(listCalls).toHaveBeenCalled());
    expect(listCalls.mock.calls[0][0]).toMatchObject({ page: 0, sort: 'createdAt', order: 'desc' });
  });
});
