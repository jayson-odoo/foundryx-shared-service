'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { FilterFieldDef, ListQuery, ListResult } from '@/types/resource';
import type { IntegrationLogItem } from '@/types/integration-logs';
import { integrationLogService } from '@/services/integration-log-service';
import { useDatetime } from '@/hooks/use-datetime';
import {
  LOG_SOURCE_REGISTRY,
  LOG_STATUS_REGISTRY,
  integrationLogDetailPath,
} from './log-badges';

/**
 * `/developers/logs` list config (sprint-4/12 AC-DLC-10) - the Integration
 * Activity console on the Resource shell. Server-side sort/filter/search/
 * paginate; source + status filter fields; per-user column prefs by viewKey.
 */
export function useIntegrationLogsListConfig(): ResourceListConfig<IntegrationLogItem> {
  const { formatDateTime } = useDatetime();

  const filterFields = useMemo<FilterFieldDef[]>(
    () => [
      {
        field: 'source',
        label: 'Source',
        type: 'enum',
        options: [
          { label: 'Inbound API', value: 'inbound_api' },
          { label: 'Embed', value: 'embed_session' },
          { label: 'Outbound', value: 'outbound_meta' },
          { label: 'Webhook', value: 'webhook_delivery' },
          { label: 'AutoCount', value: 'autocount' },
        ],
      },
      {
        field: 'status',
        label: 'Status',
        type: 'enum',
        options: [
          { label: 'Success', value: 'success' },
          { label: 'Error', value: 'error' },
          { label: 'Pending', value: 'pending' },
        ],
      },
    ],
    [],
  );

  return useMemo<ResourceListConfig<IntegrationLogItem>>(() => {
    const columns: ColumnDef<IntegrationLogItem>[] = [
      {
        id: 'source',
        accessorFn: (row) => row.source,
        meta: { headerTitle: 'Source', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={row.original.source} registry={LOG_SOURCE_REGISTRY} size="sm" />
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'operation',
        accessorFn: (row) => row.operation,
        meta: { headerTitle: 'Operation' },
        header: ({ column }) => <DataGridColumnHeader title="Operation" column={column} />,
        cell: ({ row }) => (
          <ClampedText
            className="text-foreground max-w-[280px] font-mono text-xs"
            text={row.original.operation}
          />
        ),
        size: 260,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <StatusBadge status={row.original.status} registry={LOG_STATUS_REGISTRY} size="sm" />
            {/* Typed error code (e.g. embed origin_not_allowed) reads clearer than
                the numeric status; fall back to the HTTP/Meta status code. */}
            {row.original.status === 'error' && row.original.errorCode ? (
              <span className="text-destructive font-mono text-xs">
                {row.original.errorCode}
              </span>
            ) : (
              row.original.statusCode != null && (
                <span className="text-muted-foreground text-xs">
                  {row.original.statusCode}
                </span>
              )
            )}
          </div>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'latencyMs',
        accessorFn: (row) => row.latencyMs,
        meta: { headerTitle: 'Latency' },
        header: ({ column }) => <DataGridColumnHeader title="Latency" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {row.original.latencyMs != null ? `${row.original.latencyMs} ms` : '-'}
          </span>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'workspace',
        accessorFn: (row) => row.workspaceId,
        meta: { headerTitle: 'Workspace' },
        header: ({ column }) => <DataGridColumnHeader title="Workspace" column={column} />,
        cell: ({ row }) => (
          <ClampedText
            className="text-muted-foreground max-w-[160px] font-mono text-xs"
            text={row.original.workspaceId ?? '-'}
          />
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Time' },
        header: ({ column }) => <DataGridColumnHeader title="Time" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {formatDateTime(row.original.createdAt)}
          </span>
        ),
        size: 190,
        enableSorting: true,
      },
    ];

    return {
      viewKey: 'integration-logs.list',
      columns,
      getRowId: (r) => r.id,
      rowHref: (r) => integrationLogDetailPath(r.id),
      fetcher: (q: ListQuery): Promise<ListResult<IntegrationLogItem>> =>
        integrationLogService.list(q),
      exporter: (q, cols) => integrationLogService.export(q, cols),
      filterFields,
      exportColumns: [
        { id: 'source', label: 'Source' },
        { id: 'operation', label: 'Operation' },
        { id: 'status', label: 'Status' },
        { id: 'statusCode', label: 'Status code' },
        { id: 'latencyMs', label: 'Latency (ms)' },
        { id: 'workspaceId', label: 'Workspace' },
        { id: 'traceId', label: 'Trace' },
        { id: 'externalRef', label: 'External ref' },
        { id: 'createdAt', label: 'Time' },
      ],
      actions: [],
      enableStatusViews: false,
      exportFilename: 'developer-logs',
      searchPlaceholder: 'Search operation, trace or reference…',
    };
  }, [filterFields, formatDateTime]);
}
