/**
 * AC-DLA-30 fix round 2: a restored (or delete-shrunk) page past the last
 * real page must clamp to the new last page and refetch there - never
 * commit an empty "No records" result for a page number that no longer
 * matches what should be on screen.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useResourceList } from './use-resource-list';
import { encodeListQuery } from '@/lib/list-context';
import type { ListQuery, ListResult } from '@/types/resource';

interface Row {
  id: string;
}

const { useSearchParams } = vi.hoisted(() => ({ useSearchParams: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams }));

/** A fetcher that resolves only when the test calls `resolveNext`. */
function pagedDeferredFetcher() {
  const pending: Array<{ query: ListQuery; resolve: (r: ListResult<Row>) => void }> = [];
  const fetcher = (query: ListQuery) =>
    new Promise<ListResult<Row>>((resolve) => {
      pending.push({ query, resolve });
    });
  const resolveNext = async (result: ListResult<Row>) => {
    const next = pending.shift();
    if (!next) throw new Error('no pending fetch to resolve');
    await act(async () => {
      next.resolve(result);
      // Flush the microtask chain (.then -> possible setPage -> effect ->
      // new fetcher() call) so a corrective refetch is queued in `pending`
      // by the time this resolves.
      await Promise.resolve();
      await Promise.resolve();
    });
  };
  return { fetcher, resolveNext, pendingCount: () => pending.length, pendingQueries: () => pending.map((p) => p.query) };
}

describe('AC-DLA-30 fix round 2 - out-of-range page clamps and refetches', () => {
  it('11 rows, pageSize 10, restored on page 1: deleting the last row lands on page 0 with 10 rows, never an empty page', async () => {
    const { fetcher, resolveNext, pendingCount, pendingQueries } = pagedDeferredFetcher();
    const restoredQuery: ListQuery = { page: 1, pageSize: 10, statusView: 'active' };
    useSearchParams.mockReturnValue(new URLSearchParams({ ctx: encodeListQuery(restoredQuery) }));

    const { result } = renderHook(() => useResourceList<Row>({ fetcher, restoreFromCtx: true }));

    expect(result.current.page).toBe(1);

    // Initial restore fetch: page 1 of an 11-row set has exactly 1 row.
    await resolveNext({ data: [{ id: 'r11' }], total: 11, page: 1 });
    expect(result.current.page).toBe(1);
    expect(result.current.data).toEqual([{ id: 'r11' }]);

    // Simulate "delete the last row" - the row is gone, total drops to 10;
    // the entity's own delete action calls list.reload() on the SAME page.
    act(() => result.current.reload());
    expect(pendingCount()).toBe(1);
    expect(pendingQueries()[0].page).toBe(1);

    await resolveNext({ data: [], total: 10, page: 1 });

    // Clamp fired: page moved to 0, a corrective fetch for page 0 is now
    // pending, and the row that was ALREADY on screen (r11) is still shown
    // (never cleared to []) while that corrective fetch is in flight.
    expect(result.current.page).toBe(0);
    expect(result.current.data).toEqual([{ id: 'r11' }]);
    expect(result.current.isLoading).toBe(true);
    expect(pendingCount()).toBe(1);
    expect(pendingQueries()[0].page).toBe(0);

    const tenRows = Array.from({ length: 10 }, (_, i) => ({ id: `r${i + 1}` }));
    await resolveNext({ data: tenRows, total: 10, page: 0 });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.page).toBe(0);
    expect(result.current.data).toEqual(tenRows);
    expect(result.current.total).toBe(10);
  });

  it('does not clamp when the current page is still in range', async () => {
    const { fetcher, resolveNext, pendingCount } = pagedDeferredFetcher();
    const { result } = renderHook(() => useResourceList<Row>({ fetcher }));

    await resolveNext({ data: [{ id: 'a' }], total: 1, page: 0 });
    expect(result.current.page).toBe(0);
    expect(pendingCount()).toBe(0);
  });
});
