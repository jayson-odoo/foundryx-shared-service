/**
 * AC-DLA-31: `use-record-nav.ts` resolves + prefetches the prev/next
 * neighbours' hrefs on mount (one `fetchAt` each, via the shared
 * `usePrefetchOnce`) and carries `from=<recordId>` as it steps, so the row
 * the user ends on is the one Back restores (AC-DLA-30).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import { encodeListQuery } from '@/lib/list-context';
import type { ListQuery } from '@/types/resource';
import { useRecordNav } from './use-record-nav';

const push = vi.fn();
const prefetch = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

const QUERY: ListQuery = {
  page: 0,
  pageSize: 25,
  search: '',
  sort: null,
  filter: null,
  statusView: 'active',
  segment: undefined,
};

function paramsFor(index: number, extra: Record<string, string> = {}) {
  return new URLSearchParams({ ctx: encodeListQuery(QUERY), i: String(index), ...extra });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push, prefetch } as unknown as ReturnType<typeof useRouter>);
});

describe('AC-DLA-31 use-record-nav prefetch + from carry', () => {
  it('prefetches BOTH neighbours on mount, each carrying from=<neighbour id>', async () => {
    vi.mocked(useSearchParams).mockReturnValue(paramsFor(1) as unknown as ReturnType<typeof useSearchParams>);
    // fetchAt resolves total=5 for every call; recordId = `r<index>`.
    const fetchAt = vi.fn((_q: ListQuery, index: number) =>
      Promise.resolve({ recordId: `r${index}`, total: 5 }),
    );
    const buildHref = (recordId: string, ctx: string, index: number) =>
      `/records/${recordId}?ctx=${ctx}&i=${index}`;

    renderHook(() => useRecordNav({ fetchAt, buildHref }));

    await waitFor(() => expect(prefetch).toHaveBeenCalledTimes(2));
    const prefetched = prefetch.mock.calls.map((c) => c[0] as string);
    // Prev (index 0) and next (index 2), each carrying its OWN id as `from`.
    expect(prefetched.some((h) => h.includes('/records/r0') && h.includes('from=r0'))).toBe(true);
    expect(prefetched.some((h) => h.includes('/records/r2') && h.includes('from=r2'))).toBe(true);
  });

  it('does not prefetch a neighbour when the set has only one record (total<=1)', async () => {
    vi.mocked(useSearchParams).mockReturnValue(paramsFor(0) as unknown as ReturnType<typeof useSearchParams>);
    const fetchAt = vi.fn(() => Promise.resolve({ recordId: 'r0', total: 1 }));
    const buildHref = (recordId: string, ctx: string, index: number) => `/records/${recordId}?ctx=${ctx}&i=${index}`;

    renderHook(() => useRecordNav({ fetchAt, buildHref }));

    await waitFor(() => expect(fetchAt).toHaveBeenCalled());
    expect(prefetch).not.toHaveBeenCalled();
  });

  it('goNext carries from=<the record navigated to>, updated each step', async () => {
    vi.mocked(useSearchParams).mockReturnValue(paramsFor(0) as unknown as ReturnType<typeof useSearchParams>);
    const fetchAt = vi.fn((_q: ListQuery, index: number) => {
      const wrapped = ((index % 3) + 3) % 3;
      return Promise.resolve({ recordId: `r${wrapped}`, total: 3 });
    });
    const buildHref = (recordId: string, ctx: string, index: number) => `/records/${recordId}?ctx=${ctx}&i=${index}`;

    const { result } = renderHook(() => useRecordNav({ fetchAt, buildHref }));
    await waitFor(() => expect(result.current.available).toBe(true));

    await act(async () => {
      result.current.goNext();
      await Promise.resolve();
    });

    expect(push).toHaveBeenCalledTimes(1);
    const [href] = push.mock.calls[0] as [string];
    expect(href).toContain('/records/r1');
    expect(href).toContain('from=r1');
  });
});
