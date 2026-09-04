/**
 * AC-DLA-15 (T2 half of AC-DLA-32): `useResourceList` keeps the previous
 * page's rows on screen while a refetch is in flight, exposes
 * `isPlaceholderData` (true only while stale rows are being SHOWN, false on
 * a genuine first load), and `loadedQuery` (the query the CURRENT rows
 * actually belong to - not the already-advanced live `query`).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useResourceList } from './use-resource-list';
import type { ListResult } from '@/types/resource';

interface Row {
  id: string;
}

/** A fetcher that resolves only when the test calls `resolveNext`. */
function deferredFetcher() {
  const pending: Array<{ page: number; resolve: (r: ListResult<Row>) => void }> = [];
  const fetcher = (query: { page: number }) =>
    new Promise<ListResult<Row>>((resolve) => {
      pending.push({ page: query.page, resolve });
    });
  const resolveNext = (rows: Row[]) => {
    const next = pending.shift();
    if (!next) throw new Error('no pending fetch to resolve');
    act(() => next.resolve({ data: rows, total: rows.length, page: next.page }));
  };
  return { fetcher, resolveNext, pendingCount: () => pending.length };
}

describe('AC-DLA-15/32 useResourceList placeholder data', () => {
  it('rows persist across a refetch, isPlaceholderData flips, and loadedQuery tracks the rows actually shown', async () => {
    const { fetcher, resolveNext } = deferredFetcher();
    const { result } = renderHook(() => useResourceList<Row>({ fetcher }));

    // First load: no rows yet, not a placeholder (nothing to hold).
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isPlaceholderData).toBe(false);
    expect(result.current.data).toEqual([]);

    resolveNext([{ id: 'a1' }, { id: 'a2' }]);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual([{ id: 'a1' }, { id: 'a2' }]);
    expect(result.current.isPlaceholderData).toBe(false);
    expect(result.current.loadedQuery.page).toBe(0);
    expect(result.current.query.page).toBe(0);

    // Advance to page 1 - the live query moves immediately, but the rows and
    // loadedQuery must NOT until the new fetch resolves.
    act(() => result.current.setPage(1));
    expect(result.current.query.page).toBe(1);
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data).toEqual([{ id: 'a1' }, { id: 'a2' }]); // still page 0's rows
    expect(result.current.loadedQuery.page).toBe(0); // still the page those rows came from

    resolveNext([{ id: 'b1' }, { id: 'b2' }]);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual([{ id: 'b1' }, { id: 'b2' }]);
    expect(result.current.isPlaceholderData).toBe(false);
    expect(result.current.loadedQuery.page).toBe(1);
  });
});
