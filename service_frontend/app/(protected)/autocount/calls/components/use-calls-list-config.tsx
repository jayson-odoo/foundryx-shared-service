'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { zonedTimeToUtc } from '@/lib/datetime';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCall, AutocountCallFilterOptions, CallOutcome } from '@/types/autocount';
import type { FilterGroup, ListQuery, ListResult } from '@/types/resource';
import { AC_CALL_OUTCOMES, AC_CALL_OUTCOME_REGISTRY } from '../../components/autocount-meta';

export interface CallsListConfigOptions {
  /** A row click opens the call's request and response. */
  onOpenCall?: (call: AutocountCall) => void;
}

const EMPTY_OPTIONS: AutocountCallFilterOptions = { books: [], docTypes: [], outcomes: [], persons: [] };

/** The values a multi-select (`in`) or single (`eq`) condition on `field` carries. */
function readMany(filter: FilterGroup | null | undefined, field: string): string[] | undefined {
  const rule = filter?.rules.find((r) => r.kind === 'condition' && r.field === field);
  if (!rule || rule.kind !== 'condition') return undefined;
  const value = rule.value;
  if (Array.isArray(value)) return value.length > 0 ? value : undefined;
  return typeof value === 'string' && value ? [value] : undefined;
}

/** `YYYY-MM-DD` of the day after `key`. */
function nextDayKey(key: string): string {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

/** The picked day range (viewer's timezone) as the two UTC instants the API filters on. */
function readRange(
  filter: FilterGroup | null | undefined,
  timeZone: string,
): { dateFrom?: string; dateTo?: string } {
  const rule = filter?.rules.find((r) => r.kind === 'condition' && r.field === 'createdAt');
  if (!rule || rule.kind !== 'condition' || !Array.isArray(rule.value)) return {};
  const [from, to] = rule.value;
  const start = from ? zonedTimeToUtc(`${from}T00:00:00`, timeZone) : null;
  const afterEnd = to ? zonedTimeToUtc(`${nextDayKey(to)}T00:00:00`, timeZone) : null;
  return {
    dateFrom: start ? start.toISOString() : undefined,
    dateTo: afterEnd ? new Date(afterEnd.getTime() - 1).toISOString() : undefined,
  };
}

function text(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? '-' : String(value);
}

function cell(value: string | number | null | undefined, className = 'text-sm text-foreground') {
  return <ClampedText text={text(value)} lines={1} className={className} />;
}

/**
 * The AutoCount calls log on the Resource shell (plan 63): every column sorts on the
 * server, filters are multi-select, the time range is the shared range picker, and the
 * whole query rides the address bar. A log has nothing to create.
 */
export function useCallsListConfig({ onOpenCall }: CallsListConfigOptions = {}): ResourceListConfig<AutocountCall> {
  const { formatDmyDateTime, timeZone } = useDatetime();
  const [options, setOptions] = useState<AutocountCallFilterOptions>(EMPTY_OPTIONS);
  const [companies, setCompanies] = useState<{ label: string; value: string }[]>([]);

  useEffect(() => {
    let active = true;
    void autocountService
      .getCallFilterOptions()
      .then((next) => active && setOptions(next))
      .catch(() => undefined);
    void autocountService
      .listCompanies({ page: 0, pageSize: 200 })
      .then((res) => active && setCompanies(res.data.map((c) => ({ label: c.name || c.companyName, value: c.id }))))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  // Stable across filter-option loads, so loading the option lists never refetches the page.
  const fetcher = useCallback(
    async (query: ListQuery): Promise<ListResult<AutocountCall>> => {
      const res = await autocountService.listCalls({
        page: query.page,
        pageSize: query.pageSize,
        search: query.search || undefined,
        sort: query.sort?.id,
        order: query.sort ? (query.sort.desc ? 'desc' : 'asc') : undefined,
        companyId: readMany(query.filter, 'companyId'),
        book: readMany(query.filter, 'book'),
        docType: readMany(query.filter, 'docType'),
        outcome: readMany(query.filter, 'outcome'),
        person: readMany(query.filter, 'person'),
        ...readRange(query.filter, timeZone),
      });
      return { data: res.data, total: res.total, page: query.page };
    },
    [timeZone],
  );

  return useMemo<ResourceListConfig<AutocountCall>>(() => {
    const header = (title: string): Pick<ColumnDef<AutocountCall>, 'meta' | 'header'> => ({
      meta: { headerTitle: title },
      header: ({ column }) => <DataGridColumnHeader title={title} column={column} />,
    });

    const columns: ColumnDef<AutocountCall>[] = [
      {
        id: 'createdAt',
        accessorFn: (row) => row.createdAt,
        ...header('Time'),
        cell: ({ row }) => cell(formatDmyDateTime(row.original.createdAt)),
        size: 170,
      },
      {
        id: 'companyName',
        accessorFn: (row) => row.companyName ?? '',
        ...header('Company'),
        cell: ({ row }) => cell(row.original.companyName),
        size: 160,
      },
      {
        id: 'book',
        accessorFn: (row) => row.book ?? '',
        ...header('Book'),
        cell: ({ row }) => cell(row.original.book),
        size: 80,
      },
      {
        id: 'actingUserName',
        accessorFn: (row) => row.actingUserName ?? '',
        ...header('Person'),
        cell: ({ row }) => cell(row.original.actingUserName ?? row.original.actingUserId),
        size: 150,
      },
      {
        id: 'method',
        accessorFn: (row) => row.method,
        ...header('Method'),
        cell: ({ row }) => cell(row.original.method),
        size: 90,
      },
      {
        id: 'path',
        accessorFn: (row) => row.path,
        ...header('Path'),
        cell: ({ row }) => cell(row.original.path),
        size: 220,
      },
      {
        id: 'docType',
        accessorFn: (row) => row.docType ?? '',
        ...header('Document type'),
        cell: ({ row }) => cell(row.original.docType),
        size: 120,
      },
      {
        id: 'docNo',
        accessorFn: (row) => row.docNo ?? '',
        ...header('Document no'),
        cell: ({ row }) => cell(row.original.docNo),
        size: 130,
      },
      {
        id: 'outcome',
        accessorFn: (row) => row.outcome,
        ...header('Outcome'),
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.outcome as CallOutcome}
            registry={AC_CALL_OUTCOME_REGISTRY}
            size="sm"
            className="whitespace-nowrap"
          />
        ),
        size: 170,
      },
      {
        id: 'responseStatus',
        accessorFn: (row) => row.responseStatus ?? 0,
        ...header('HTTP status'),
        cell: ({ row }) => cell(row.original.responseStatus, 'text-sm tabular-nums text-muted-foreground'),
        size: 110,
      },
      {
        id: 'durationMs',
        accessorFn: (row) => row.durationMs,
        ...header('Duration'),
        cell: ({ row }) => cell(`${row.original.durationMs} ms`, 'text-sm tabular-nums text-muted-foreground'),
        size: 100,
      },
      {
        id: 'errorCode',
        accessorFn: (row) => row.errorCode ?? '',
        ...header('Error'),
        cell: ({ row }) => cell(row.original.errorCode, 'text-sm text-destructive'),
        size: 180,
      },
      {
        id: 'requestId',
        accessorFn: (row) => row.requestId ?? '',
        ...header('Request id'),
        cell: ({ row }) => cell(row.original.requestId, 'text-sm text-muted-foreground'),
        size: 180,
      },
    ];

    return {
      viewKey: 'autocount.calls.list',
      pageTitle: 'AutoCount calls',
      columns,
      getRowId: (row) => row.id,
      rowHref: () => '#',
      onRowSelect: (row) => onOpenCall?.(row),
      urlState: true,
      searchPlaceholder: 'Search document no, request id or path',
      defaultSort: { id: 'createdAt', desc: true },
      enableStatusViews: false,
      filterFields: [
        { field: 'createdAt', label: 'Time', type: 'date' },
        { field: 'companyId', label: 'Company', type: 'enum', options: companies },
        { field: 'book', label: 'Book', type: 'enum', options: options.books.map((b) => ({ label: b, value: b })) },
        {
          field: 'docType',
          label: 'Document type',
          type: 'enum',
          options: options.docTypes.map((t) => ({ label: t, value: t })),
        },
        {
          field: 'outcome',
          label: 'Outcome',
          type: 'enum',
          options: AC_CALL_OUTCOMES.map((o) => ({ label: AC_CALL_OUTCOME_REGISTRY[o].label, value: o })),
        },
        {
          field: 'person',
          label: 'Person',
          type: 'enum',
          options: options.persons.map((p) => ({ label: p.name || p.id, value: p.id })),
        },
      ],
      exportColumns: [],
      actions: [],
      fetcher,
    };
  }, [formatDmyDateTime, fetcher, options, companies, onOpenCall]);
}
