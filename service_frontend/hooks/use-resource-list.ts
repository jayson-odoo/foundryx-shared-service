'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import type { FilterGroup, ListQuery, ListResult, SortState, StatusView } from '@/types/resource';
import { decodeListQuery } from '@/lib/list-context';
import { useDebounce } from './use-debounce';

export interface UseResourceListOptions<T> {
  fetcher: (query: ListQuery) => Promise<ListResult<T>>;
  defaultPageSize?: number;
  defaultSort?: SortState | null;
  /** Initial segment when the entity uses N-way segments (see ListQuery.segment). */
  defaultSegment?: string;
  /**
   * AC-DLA-30 fix round 1 (Back restores the row past page one): when true,
   * the hook's initial page/pageSize/search/sort/filter/statusView/segment
   * are read off the `ctx` query param (`decodeListQuery`) if present and
   * decodable, falling back to the usual defaults otherwise. Read exactly
   * ONCE, at mount (a `useState` lazy initializer) - a later `ctx` edit in
   * the URL never re-seeds an already-mounted list. Callers embedding a
   * `ResourceList` inside a RECORD's own tab must leave this off: that URL's
   * `ctx` belongs to the outer record's pager (`use-record-nav.ts`), not to
   * the tab's own list - `ResourceList` defaults it to `!hideHeader` for
   * exactly this reason.
   */
  restoreFromCtx?: boolean;
}

export interface UseResourceListResult<T> {
  /** The live query (search reflects the DEBOUNCED value) - used for export + record-nav ctx. */
  query: ListQuery;
  /**
   * The query that produced the CURRENT `data` (AC-DLA-15/32, T2 half).
   * While a refetch is in flight `query` has already advanced (new page/
   * sort/filter/search) but `data` still holds the PREVIOUS result - a
   * caller computing a row's global index (or anything else keyed to "which
   * page are these rows actually from") must read `loadedQuery`, not
   * `query`, or it mis-indexes the still-showing stale rows against the
   * new page number.
   */
  loadedQuery: ListQuery;
  data: T[];
  total: number;
  isLoading: boolean;
  /**
   * True while `isLoading` AND the previous page's rows are still on screen
   * (AC-DLA-15) - `DataGrid` dims the body instead of showing a skeleton.
   * False on a genuine first load (no rows to hold yet).
   */
  isPlaceholderData: boolean;
  error: string | null;

  page: number;
  pageSize: number;
  search: string; // raw (immediate) input value
  sort: SortState | null;
  filter: FilterGroup | null;
  statusView: StatusView;
  segment: string | undefined;

  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  setSearch: (search: string) => void;
  setSort: (sort: SortState | null) => void;
  setFilter: (filter: FilterGroup | null) => void;
  setStatusView: (view: StatusView) => void;
  setSegment: (segment: string) => void;
  reload: () => void;
}

/**
 * Owns server-side list state (pagination/sort/filter/search/status-view),
 * fetches via the entity service, and resets to page 0 when the result set
 * changes. The Resource shell consumes this; entities never reimplement it.
 */
export function useResourceList<T>({
  fetcher,
  defaultPageSize = 25,
  defaultSort = null,
  defaultSegment,
  restoreFromCtx = false,
}: UseResourceListOptions<T>): UseResourceListResult<T> {
  const searchParams = useSearchParams();
  // Lazy initializer runs exactly once, at mount - the whole point (a later
  // `ctx` change from record-nav stepping must never re-seed this list).
  const [restored] = useState<ListQuery | null>(() =>
    restoreFromCtx ? decodeListQuery(searchParams.get('ctx')) : null,
  );

  const [page, setPage] = useState(restored?.page ?? 0);
  const [pageSize, setPageSizeState] = useState(restored?.pageSize ?? defaultPageSize);
  const [search, setSearchState] = useState(restored?.search ?? '');
  const [sort, setSortState] = useState<SortState | null>(restored?.sort ?? defaultSort);
  const [filter, setFilterState] = useState<FilterGroup | null>(restored?.filter ?? null);
  const [statusView, setStatusViewState] = useState<StatusView>(restored?.statusView ?? 'active');
  const [segment, setSegmentState] = useState<string | undefined>(restored?.segment ?? defaultSegment);

  const [data, setData] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const debouncedSearch = useDebounce(search, 300);

  const query = useMemo<ListQuery>(
    () => ({ page, pageSize, search: debouncedSearch, sort, filter, statusView, segment }),
    [page, pageSize, debouncedSearch, sort, filter, statusView, segment],
  );

  // The query that produced the rows CURRENTLY in `data` - starts equal to
  // the first query, only ever reassigned once a fetch for a NEWER query
  // resolves (see the effect below). Never read `query` for "which page are
  // these rows from" while `isPlaceholderData` is true.
  const [loadedQuery, setLoadedQuery] = useState<ListQuery>(query);

  // Reset to first page whenever the result set (not just the page) changes.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    setPage(0);
  }, [debouncedSearch, sort, filter, statusView, segment, pageSize]);

  useEffect(() => {
    let active = true;
    // Fix round 2: set inside `.then` when this fetch's page turns out to be
    // past the last real page - a restored `ctx` naming a page that no
    // longer exists once rows were deleted elsewhere, or a page whose only
    // remaining row was just deleted. Guards `finally` so `isLoading` stays
    // true straight through the hand-off to the corrected-page refetch
    // (below) - the rows already on screen (from BEFORE this fetch cycle)
    // keep showing, dimmed, instead of the grid ever committing this now-
    // empty/wrong-page result and flashing (or sticking on) "No records".
    let clamping = false;
    setIsLoading(true);
    fetcher(query)
      .then((result) => {
        if (!active) return;
        if (query.page > 0 && query.pageSize > 0 && query.page * query.pageSize >= result.total) {
          const clamped = Math.max(0, Math.ceil(result.total / query.pageSize) - 1);
          if (clamped !== query.page) {
            clamping = true;
            setPage(clamped);
            return;
          }
        }
        setData(result.data);
        setTotal(result.total);
        setError(null);
        // This query is now the one the rows on screen belong to - flips
        // `isPlaceholderData` off for it and lets a caller trust `loadedQuery`
        // for indexing again.
        setLoadedQuery(query);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : 'Failed to load.');
      })
      .finally(() => {
        if (active && !clamping) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [fetcher, query, reloadKey]);

  const isPlaceholderData = isLoading && data.length > 0;

  const setPageSize = useCallback((size: number) => setPageSizeState(size), []);
  const setSearch = useCallback((value: string) => setSearchState(value), []);
  const setSort = useCallback((value: SortState | null) => setSortState(value), []);
  const setFilter = useCallback((value: FilterGroup | null) => setFilterState(value), []);
  const setStatusView = useCallback((view: StatusView) => setStatusViewState(view), []);
  const setSegment = useCallback((value: string) => setSegmentState(value), []);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  return {
    query,
    loadedQuery,
    data,
    total,
    isLoading,
    isPlaceholderData,
    error,
    page,
    pageSize,
    search,
    sort,
    filter,
    statusView,
    segment,
    setPage,
    setPageSize,
    setSearch,
    setSort,
    setFilter,
    setStatusView,
    setSegment,
    reload,
  };
}
