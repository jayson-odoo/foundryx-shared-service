/**
 * AC-DLA-30 fix round 1: `useResourceList({ restoreFromCtx: true })` seeds
 * its initial page/pageSize/search/sort/filter/statusView/segment from the
 * URL's `ctx` param (`decodeListQuery`) when present, so a list mounted via
 * Back lands exactly where the user left it - not back at page one. Without
 * a `ctx` (or with `restoreFromCtx` left off, the embedded-list default), it
 * falls back to the hook's usual defaults.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useResourceList } from './use-resource-list';
import { encodeListQuery } from '@/lib/list-context';
import type { ListQuery, ListResult } from '@/types/resource';

interface Row {
  id: string;
}

const { useSearchParams } = vi.hoisted(() => ({ useSearchParams: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams }));

const neverResolves = () => new Promise<ListResult<Row>>(() => {});

describe('AC-DLA-30 useResourceList ctx restore', () => {
  it('with a ctx param and restoreFromCtx: true, the initial query equals the decoded ctx', () => {
    const query: ListQuery = {
      page: 3,
      pageSize: 50,
      search: 'orange',
      sort: { id: 'name', desc: true },
      filter: null,
      statusView: 'trashed',
      segment: undefined,
    };
    useSearchParams.mockReturnValue(new URLSearchParams({ ctx: encodeListQuery(query) }));

    const { result } = renderHook(() =>
      useResourceList<Row>({ fetcher: neverResolves, restoreFromCtx: true }),
    );

    expect(result.current.page).toBe(3);
    expect(result.current.pageSize).toBe(50);
    expect(result.current.search).toBe('orange');
    expect(result.current.sort).toEqual({ id: 'name', desc: true });
    expect(result.current.statusView).toBe('trashed');
  });

  it('without a ctx param, restoreFromCtx: true falls back to the usual defaults', () => {
    useSearchParams.mockReturnValue(new URLSearchParams());

    const { result } = renderHook(() =>
      useResourceList<Row>({ fetcher: neverResolves, restoreFromCtx: true, defaultPageSize: 25 }),
    );

    expect(result.current.page).toBe(0);
    expect(result.current.pageSize).toBe(25);
    expect(result.current.search).toBe('');
    expect(result.current.sort).toBeNull();
    expect(result.current.statusView).toBe('active');
  });

  it('with a ctx param but restoreFromCtx left off (the embedded-list default), the ctx is ignored', () => {
    const query: ListQuery = { page: 7, pageSize: 100, statusView: 'active' };
    useSearchParams.mockReturnValue(new URLSearchParams({ ctx: encodeListQuery(query) }));

    const { result } = renderHook(() =>
      useResourceList<Row>({ fetcher: neverResolves, defaultPageSize: 25 }),
    );

    expect(result.current.page).toBe(0);
    expect(result.current.pageSize).toBe(25);
  });
});
