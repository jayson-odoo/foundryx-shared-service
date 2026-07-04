'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { LayoutGrid } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { workspaceService } from '@/services/workspace-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { Workspace } from '@/types/omnichannel';
import { WORKSPACE_STATUS_REGISTRY } from './workspace-status';
import { useWorkspaceActions } from './use-workspace-actions';
import { workspaceFormPath, workspaceNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [
      { label: 'Active', value: 'ACTIVE' },
      { label: 'Inactive', value: 'INACTIVE' },
    ],
  },
  { field: 'created', label: 'Created', type: 'date' },
];

export function useWorkspacesListConfig(): ResourceListConfig<Workspace> {
  const { formatDate } = useDatetime();
  const router = useRouter();
  const actions = useWorkspaceActions();

  return useMemo<ResourceListConfig<Workspace>>(() => {
    const columns: ColumnDef<Workspace>[] = [
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
        meta: { headerTitle: 'Workspace' },
        header: ({ column }) => <DataGridColumnHeader title="Workspace" column={column} />,
        cell: ({ row }) => {
          const w = row.original;
          return (
            <div className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                <LayoutGrid className="size-4" />
              </span>
              <span className="font-medium text-foreground">{w.name}</span>
              {w.isDefault && (
                <Badge variant="secondary" appearance="light" size="sm">
                  Default
                </Badge>
              )}
            </div>
          );
        },
        size: 300,
        enableSorting: true,
      },
      {
        id: 'channels',
        accessorFn: (row) => row.channelCount,
        meta: { headerTitle: 'Channels' },
        header: ({ column }) => <DataGridColumnHeader title="Channels" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.channelCount}</span>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'members',
        accessorFn: (row) => row.memberCount,
        meta: { headerTitle: 'Members' },
        header: ({ column }) => <DataGridColumnHeader title="Members" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.memberCount}</span>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={row.original.status} registry={WORKSPACE_STATUS_REGISTRY} />
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 150,
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
                runtime={{ ctx: meta?.resourceCtx, index, reload: meta?.reload ?? (() => {}) }}
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
      viewKey: 'omnichannel.workspaces.list',
      columns,
      getRowId: (w) => w.id,
      rowHref: (w) => workspaceFormPath(w.id),
      fetcher: (q) => workspaceService.list(q),
      exporter: (q, cols, ids) => workspaceService.exportCsv(q, cols, ids),
      filterFields: FILTER_FIELDS,
      exportColumns: [
        { id: 'name', label: 'Workspace' },
        { id: 'channels', label: 'Channels' },
        { id: 'members', label: 'Members' },
        { id: 'status', label: 'Status' },
        { id: 'created', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search workspaces…',
      searchHints: ['Name'],
      defaultSort: { id: 'created', desc: true },
      enableStatusViews: true,
      exportFilename: 'workspaces',
      createLabel: 'New workspace',
      createPermission: 'workspaces.manage',
      onCreate: () => router.push(workspaceNewPath),
    };
  }, [actions, router, formatDate]);
}
