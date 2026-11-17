'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ResourceList, type ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { matchesFilterGroup, type ClientFilterValue } from '@/lib/client-filter';
import { toCsv } from '@/lib/csv';
import type { FilterFieldDef, ListQuery, ListResult } from '@/types/resource';
import type { HistoryEntry } from '@/types/record-history';

const DASH = '-';

const SORT_KEYS: Record<string, (r: HistoryEntry) => string> = {
  at: (r) => r.at ?? '',
  who: (r) => (r.who ?? '').toLowerCase(),
  onBehalfOf: (r) => (r.onBehalfOf ?? '').toLowerCase(),
  action: (r) => r.action.toLowerCase(),
  from: (r) => (r.from ?? '').toLowerCase(),
  to: (r) => (r.to ?? '').toLowerCase(),
};

function filterValue(r: HistoryEntry, field: string): ClientFilterValue {
  if (field === 'at') return r.at;
  if (field === 'who') return r.who;
  if (field === 'onBehalfOf') return r.onBehalfOf;
  if (field === 'action') return r.action;
  return null;
}

/** One page of a (small, fully loaded) history: search, filter, sort. Newest
 * first unless a column sort is chosen. */
export function historyPage(rows: HistoryEntry[], query: ListQuery): ListResult<HistoryEntry> {
  let data = rows;
  if (query.search) {
    const s = query.search.toLowerCase();
    data = data.filter((r) =>
      [r.who, r.onBehalfOf, r.action, r.from, r.to].some((v) => (v ?? '').toLowerCase().includes(s)),
    );
  }
  data = data.filter((r) => matchesFilterGroup(r, query.filter, filterValue));
  const sort = query.sort ?? { id: 'at', desc: true };
  const key = SORT_KEYS[sort.id];
  if (key) {
    const dir = sort.desc ? -1 : 1;
    data = [...data].sort((a, b) => dir * key(a).localeCompare(key(b)));
  }
  const start = query.page * query.pageSize;
  return { data: data.slice(start, start + query.pageSize), total: data.length, page: query.page };
}

const COLUMNS: { id: keyof typeof SORT_KEYS; title: string; size: number }[] = [
  { id: 'at', title: 'When', size: 200 },
  { id: 'who', title: 'Who', size: 160 },
  { id: 'onBehalfOf', title: 'On behalf of', size: 150 },
  { id: 'action', title: 'Action', size: 170 },
  { id: 'from', title: 'From', size: 200 },
  { id: 'to', title: 'To', size: 200 },
];

export interface RecordHistoryProps {
  /** Per-user column preferences key, e.g. `ideation.idea.history`. */
  viewKey: string;
  /** Loads the record's whole history (records keep it small). */
  load: () => Promise<HistoryEntry[]>;
}

/**
 * The shared History view of a record (owner standing rule: every tracked
 * action shows here - who, on behalf of, when, plain action, old -> new), on
 * the standard list shell: search, filters, sortable columns, column choice,
 * export. Values the system never recorded read "-".
 */
export function RecordHistory({ viewKey, load }: RecordHistoryProps) {
  const { formatDmyDateTime } = useDatetime();
  const [rows, setRows] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    load()
      .then((r) => active && setRows(r))
      .catch(() => {
        if (!active) return;
        setRows(null);
        setError('Could not load the history.');
      });
    return () => {
      active = false;
    };
  }, [load, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  // Actions can happen in another window (a contact following from their own
  // board): refetch when this window regains focus.
  useEffect(() => {
    window.addEventListener('focus', reload);
    return () => window.removeEventListener('focus', reload);
  }, [reload]);

  const config = useMemo<ResourceListConfig<HistoryEntry>>(() => {
    const data = rows ?? [];
    const text = (r: HistoryEntry, id: string): string => {
      if (id === 'at') return r.at ? formatDmyDateTime(r.at) : DASH;
      const v = r[id as keyof HistoryEntry];
      return v ? String(v) : DASH;
    };
    const columns: ColumnDef<HistoryEntry>[] = COLUMNS.map((c) => ({
      id: c.id,
      accessorFn: (r: HistoryEntry) => SORT_KEYS[c.id](r),
      meta: { headerTitle: c.title },
      header: ({ column }) => <DataGridColumnHeader title={c.title} column={column} />,
      cell: ({ row }) => <ClampedText text={text(row.original, c.id)} lines={1} />,
      size: c.size,
    }));
    const actions = Array.from(new Set(data.map((r) => r.action))).sort();
    const filterFields: FilterFieldDef[] = [
      { field: 'action', label: 'Action', type: 'enum', options: actions.map((a) => ({ label: a, value: a })) },
      { field: 'who', label: 'Who', type: 'text' },
      { field: 'onBehalfOf', label: 'On behalf of', type: 'text' },
      { field: 'at', label: 'When', type: 'date' },
    ];
    return {
      viewKey,
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher: async (query: ListQuery) => historyPage(data, query),
      exporter: async (query, cols, ids) => {
        const picked = COLUMNS.filter((c) => cols.includes(c.id));
        const all = historyPage(data, { ...query, page: 0, pageSize: 100_000 }).data;
        const chosen = ids && ids.length ? all.filter((r) => ids.includes(r.id)) : all;
        return toCsv(
          picked.map((c) => c.title),
          chosen.map((r) => picked.map((c) => text(r, c.id))),
        );
      },
      exportFilename: 'history',
      searchPlaceholder: 'Search history…',
      enableStatusViews: false,
      columns,
      filterFields,
      exportColumns: COLUMNS.map((c) => ({ id: c.id, label: c.title })),
      actions: [],
    };
  }, [rows, viewKey, formatDmyDateTime]);

  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-destructive" role="alert">
          <span>{error}</span>
          <Button mode="link" size="sm" onClick={reload}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (rows === null) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12 text-muted-foreground">
          <LoaderCircleIcon className="size-5 animate-spin" />
        </CardContent>
      </Card>
    );
  }
  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">No history yet.</CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="py-4">
        <ResourceList key={rows.length} config={config} hideHeader />
      </CardContent>
    </Card>
  );
}
