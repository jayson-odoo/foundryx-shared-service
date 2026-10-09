'use client';

import { useMemo } from 'react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectorCall } from '@/types/connector';

type Col = { id: keyof ConnectorCall; title: string; size: number };

const PLAIN_COLUMNS: Col[] = [
  { id: 'statusCode', title: 'Code', size: 80 },
  { id: 'rows', title: 'Rows', size: 80 },
  { id: 'chars', title: 'Chars', size: 90 },
  { id: 'ms', title: 'ms', size: 80 },
];

/** Activity calls on the Resource shell: a client-side page over the loaded calls. */
export function useConnectorActivityListConfig(
  calls: ConnectorCall[],
): ResourceListConfig<ConnectorCall> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<ConnectorCall>>(
    () => ({
      viewKey: 'claude-connector-activity',
      getRowId: (row) => row.id,
      rowHref: () => '#',
      fetcher: async (query) => {
        const start = query.page * query.pageSize;
        return {
          data: calls.slice(start, start + query.pageSize),
          total: calls.length,
          page: query.page,
        };
      },
      defaultView: 'list',
      columns: [
        {
          id: 'at',
          accessorFn: (row) => row.at,
          meta: { headerTitle: 'Time' },
          header: ({ column }) => <DataGridColumnHeader title="Time" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">{formatDateTime(row.original.at)}</span>
          ),
          size: 170,
          enableSorting: false,
        },
        {
          id: 'tool',
          accessorFn: (row) => row.tool,
          meta: { headerTitle: 'Tool' },
          header: ({ column }) => <DataGridColumnHeader title="Tool" column={column} />,
          cell: ({ row }) => <code className="text-xs">{row.original.tool}</code>,
          size: 180,
          enableSorting: false,
        },
        ...PLAIN_COLUMNS.map((c) => ({
          id: c.id,
          accessorFn: (row: ConnectorCall) => row[c.id],
          meta: { headerTitle: c.title },
          header: ({ column }: { column: import('@tanstack/react-table').Column<ConnectorCall> }) => (
            <DataGridColumnHeader title={c.title} column={column} />
          ),
          cell: ({ row }: { row: import('@tanstack/react-table').Row<ConnectorCall> }) => (
            <span className="text-sm">{String(row.original[c.id])}</span>
          ),
          size: c.size,
          enableSorting: false,
        })),
        {
          id: 'result',
          accessorFn: (row) => row.truncated,
          meta: { headerTitle: 'Result' },
          header: ({ column }) => <DataGridColumnHeader title="Result" column={column} />,
          cell: ({ row }) =>
            row.original.truncated ? (
              <Badge variant="warning" appearance="light" size="sm">
                Truncated
              </Badge>
            ) : null,
          size: 110,
          enableSorting: false,
        },
      ],
      filterFields: [],
      exportColumns: [],
      actions: [],
    }),
    [calls, formatDateTime],
  );
}
