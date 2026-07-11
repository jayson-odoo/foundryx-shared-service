'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { StatusBadge } from '@/components/platform/status-badge';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { integrationService } from '@/services/integration-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { Connection, IntegrationProvider } from '@/types/integration';
import { CONNECTION_STATUS_REGISTRY } from './connection-status';
import { useConnectionActions } from './use-connection-actions';
import { connectionFormPath, connectionNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const TYPE_LABELS: Record<string, string> = {
  email: 'Email',
  storage: 'Storage',
  llm: 'LLM',
  erp: 'ERP',
};

const STATIC_FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  {
    field: 'type',
    label: 'Type',
    type: 'enum',
    options: Object.entries(TYPE_LABELS).map(([value, label]) => ({ label, value })),
  },
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [
      { label: 'Connected', value: 'ACTIVE' },
      { label: 'Unverified', value: 'UNVERIFIED' },
      { label: 'Error', value: 'ERROR' },
    ],
  },
  { field: 'lastTestedAt', label: 'Last tested', type: 'date' },
  { field: 'created', label: 'Created', type: 'date' },
];

export function useConnectionsListConfig(): ResourceListConfig<Connection> {
  // Session-tz formatters (plan sprint-2/05) — never the tz-blind lib/format.
  const { formatDate, formatDateTime } = useDatetime();
  const router = useRouter();
  const actions = useConnectionActions();
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);

  // Provider filter options + title lookup come from the live catalog.
  useEffect(() => {
    integrationService.providers().then(setProviders).catch(() => setProviders([]));
  }, []);

  const providerTitle = useMemo(() => {
    const map = new Map(providers.map((p) => [p.provider, p.title]));
    return (key: string) => map.get(key) ?? key;
  }, [providers]);

  const filterFields = useMemo<FilterFieldDef[]>(
    () => [
      STATIC_FILTER_FIELDS[0],
      {
        field: 'provider',
        label: 'Provider',
        type: 'enum',
        options: providers.map((p) => ({ label: p.title, value: p.provider })),
      },
      ...STATIC_FILTER_FIELDS.slice(1),
    ],
    [providers],
  );

  return useMemo<ResourceListConfig<Connection>>(() => {
    const columns: ColumnDef<Connection>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="flex items-center gap-2 font-medium text-foreground leading-tight">
              {row.original.name}
              {row.original.type === 'storage' && row.original.isActive && (
                <Badge variant="success" appearance="light" size="sm">
                  Active
                </Badge>
              )}
            </span>
            <span className="text-xs text-muted-foreground">
              {providerTitle(row.original.provider)}
            </span>
          </div>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'type',
        accessorFn: (row) => row.type,
        meta: { headerTitle: 'Type' },
        header: ({ column }) => <DataGridColumnHeader title="Type" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {TYPE_LABELS[row.original.type] ?? row.original.type}
          </span>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.status}
            registry={CONNECTION_STATUS_REGISTRY}
          />
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'lastTestedAt',
        accessorFn: (row) => row.lastTestedAt,
        meta: { headerTitle: 'Last tested' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Last tested" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastTestedAt
              ? formatDateTime(row.original.lastTestedAt)
              : 'Never'}
          </span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'lastError',
        accessorFn: (row) => row.lastError,
        meta: { headerTitle: 'Last error' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Last error" column={column} />
        ),
        cell: ({ row }) =>
          row.original.lastError ? (
            <ClampedText
              text={row.original.lastError}
              lines={1}
              className="text-sm text-destructive"
            />
          ) : (
            <span className="text-sm text-muted-foreground">—</span>
          ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {formatDate(row.original.createdAt)}
          </span>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{
                  ctx: meta?.resourceCtx,
                  index,
                  reload: meta?.reload ?? (() => {}),
                }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'connections.list',
      columns,
      getRowId: (c) => c.id,
      rowHref: (c) => connectionFormPath(c.id),
      fetcher: (q) => integrationService.list(q),
      exporter: (q, cols, ids) => integrationService.exportCsv(q, cols, ids),
      filterFields,
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'provider', label: 'Provider' },
        { id: 'type', label: 'Type' },
        { id: 'status', label: 'Status' },
        { id: 'lastTestedAt', label: 'Last tested' },
        { id: 'lastError', label: 'Last error' },
        { id: 'created', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search integrations…',
      searchHints: ['Name', 'Provider', 'Last error'],
      defaultSort: { id: 'created', desc: true },
      // Connections have no soft-trash — disconnect is final (plan 09).
      enableStatusViews: false,
      exportFilename: 'integrations',
      createLabel: 'Connect integration',
      createPermission: 'integrations.manage',
      onCreate: () => router.push(connectionNewPath),
    };
  }, [actions, router, filterFields, providerTitle]);
}
