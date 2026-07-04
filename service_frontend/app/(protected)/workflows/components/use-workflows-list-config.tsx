'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { RunStatusBadge } from '@/components/platform/workflow-runs';
import { useDatetime } from '@/hooks/use-datetime';
import { workflowService } from '@/services/workflow-service';
import type { WorkflowListItem } from '@/types/workflows';
import { WORKFLOWS_PATH, workflowPath } from './paths';
import { useWorkflowActions } from './use-workflow-actions';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function useWorkflowsListConfig(): ResourceListConfig<WorkflowListItem> {
  const router = useRouter();
  const actions = useWorkflowActions();
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<WorkflowListItem>>(() => {
    const columns: ColumnDef<WorkflowListItem>[] = [
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
            <span className="font-medium leading-tight text-foreground">{row.original.name}</span>
            <ClampedText
              text={row.original.description}
              lines={1}
              className="text-xs text-muted-foreground"
            />
          </div>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'isActive',
        accessorFn: (row) => row.isActive,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <Badge variant={row.original.isActive ? 'success' : 'secondary'} appearance="light" size="sm">
            {row.original.isActive ? 'Active' : 'Inactive'}
          </Badge>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'published',
        accessorFn: (row) => row.currentVersionNumber,
        meta: { headerTitle: 'Published' },
        header: ({ column }) => <DataGridColumnHeader title="Published" column={column} />,
        cell: ({ row }) => {
          const { currentVersionNumber, hasUnpublishedChanges } = row.original;
          if (currentVersionNumber == null) {
            return <span className="text-xs text-muted-foreground">Not published</span>;
          }
          return (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-foreground">v{currentVersionNumber}</span>
              {hasUnpublishedChanges ? (
                <Badge variant="warning" appearance="light" size="sm">
                  Unpublished changes
                </Badge>
              ) : (
                <Badge variant="success" appearance="light" size="sm">
                  Published
                </Badge>
              )}
            </div>
          );
        },
        size: 200,
        enableSorting: true,
      },
      {
        id: 'triggerLabel',
        accessorFn: (row) => row.triggerLabel,
        meta: { headerTitle: 'Trigger' },
        header: ({ column }) => <DataGridColumnHeader title="Trigger" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.triggerLabel}</span>,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'lastRunAt',
        accessorFn: (row) => row.lastRunAt,
        meta: { headerTitle: 'Last run' },
        header: ({ column }) => <DataGridColumnHeader title="Last run" column={column} />,
        cell: ({ row }) =>
          row.original.lastRunAt ? (
            <div className="flex items-center gap-1.5">
              {row.original.lastRunStatus && <RunStatusBadge status={row.original.lastRunStatus} size="sm" />}
              <span className="text-xs text-muted-foreground">{formatDateTime(row.original.lastRunAt)}</span>
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">Never</span>
          ),
        size: 190,
        enableSorting: false,
      },
      {
        id: 'updatedAt',
        accessorFn: (row) => row.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDateTime(row.original.updatedAt)}</span>
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
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ reload: meta?.reload ?? (() => {}) }}
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
      viewKey: 'workflows',
      getRowId: (row) => row.id,
      rowHref: (row) => workflowPath(row.id),
      fetcher: (query) => workflowService.list(query),
      exporter: (query, exportColumns) => workflowService.export(query, exportColumns),
      searchPlaceholder: 'Search workflows…',
      searchHints: ['Name', 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'workflows',
      createLabel: 'New workflow',
      createPermission: 'workflows.manage',
      onCreate: () => router.push(`${WORKFLOWS_PATH}/new`),
      statusViewLabels: { active: 'Active', trashed: 'Archived' },
      columns,
      filterFields: [
        { field: 'name', label: 'Name', type: 'text' },
        {
          field: 'isActive',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Active', value: 'true' },
            { label: 'Inactive', value: 'false' },
          ],
        },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'triggerLabel', label: 'Trigger' },
        { id: 'isActive', label: 'Active' },
        { id: 'currentVersionNumber', label: 'Version' },
        { id: 'updatedAt', label: 'Updated' },
      ],
      actions,
    };
  }, [actions, router, formatDateTime]);
}
