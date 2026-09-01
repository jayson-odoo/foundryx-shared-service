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
  data: T[];
  total: number;
  isLoading: boolean;
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

  const setPageSize = useCallback((size: number) => setPageSizeState(size), []);
  const setSearch = useCallback((value: string) => setSearchState(value), []);
  const setSort = useCallback((value: SortState | null) => setSortState(value), []);
  const setFilter = useCallback((value: FilterGroup | null) => setFilterState(value), []);
  const setStatusView = useCallback((view: StatusView) => setStatusViewState(view), []);
  const setSegment = useCallback((value: string) => setSegmentState(value), []);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  return {
    query,
    data,
    total,
    isLoading,
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
