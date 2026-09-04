'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FilterGroup, ListQuery, ListResult, SortState, StatusView } from '@/types/resource';
import { useDebounce } from './use-debounce';

export interface UseResourceListOptions<T> {
  fetcher: (query: ListQuery) => Promise<ListResult<T>>;
  defaultPageSize?: number;
  defaultSort?: SortState | null;
  /** Initial segment when the entity uses N-way segments (see ListQuery.segment). */
  defaultSegment?: string;
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
}: UseResourceListOptions<T>): UseResourceListResult<T> {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSizeState] = useState(defaultPageSize);
  const [search, setSearchState] = useState('');
  const [sort, setSortState] = useState<SortState | null>(defaultSort);
  const [filter, setFilterState] = useState<FilterGroup | null>(null);
  const [statusView, setStatusViewState] = useState<StatusView>('active');
  const [segment, setSegmentState] = useState<string | undefined>(defaultSegment);

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
    setIsLoading(true);
    fetcher(query)
      .then((result) => {
        if (!active) return;
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
        if (active) setIsLoading(false);
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
