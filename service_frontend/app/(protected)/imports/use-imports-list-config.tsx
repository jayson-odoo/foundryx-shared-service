'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { importService } from '@/services/import-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { ListQuery, ListResult } from '@/types/resource';
import type { ImportJob } from '@/types/import';

const STATUS_TONE: Record<string, 'success' | 'destructive' | 'secondary' | 'primary'> = {
  done: 'success',
  failed: 'destructive',
  validated: 'primary',
};

/**
 * `/imports` list config (AC-DLA-56, T7) - the bulk-import history, moved
 * onto the Resource shell (it IS a paginated server list - `importService.list`
 * already takes page/pageSize, just never wired through `ResourceList`).
 * No search/filter/sort server-side (the backend list endpoint doesn't
 * support them yet); matches `/jobs`' equivalent history list.
 */
export function useImportsListConfig(): ResourceListConfig<ImportJob> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<ImportJob>>(() => {
    const columns: ColumnDef<ImportJob>[] = [
      {
        id: 'entityType',
        accessorFn: (row) => row.entityType,
        meta: { headerTitle: 'Entity' },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) => <span className="text-foreground text-sm font-medium">{row.original.entityType}</span>,
        size: 160,
        enableSorting: false,
      },
      {
        id: 'mode',
        accessorFn: (row) => row.mode,
        meta: { headerTitle: 'Mode' },
        header: ({ column }) => <DataGridColumnHeader title="Mode" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground text-sm">{row.original.mode}</span>,
        size: 140,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <Badge variant={STATUS_TONE[row.original.status] ?? 'secondary'} appearance="light">
            {row.original.status}
          </Badge>
        ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'rows',
        meta: { headerTitle: 'Rows' },
        header: ({ column }) => <DataGridColumnHeader title="Rows" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums">
            {row.original.validRows}/{row.original.totalRows}
          </span>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">{formatDateTime(row.original.createdAt)}</span>
        ),
        size: 190,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'imports.list',
      pageDescription: 'Bulk-import history across your workspace.',
      columns,
      getRowId: (j) => j.id,
      rowHref: (j) => `/imports/${j.id}`,
      fetcher: (q: ListQuery): Promise<ListResult<ImportJob>> =>
        importService
          .list({ page: q.page, pageSize: q.pageSize })
          .then((r) => ({ data: r.items, total: r.total, page: q.page })),
      filterFields: [],
      exportColumns: [],
      actions: [],
      enableStatusViews: false,
    };
  }, [formatDateTime]);
}
