'use client';

/** Migration job history list (AC-MIG-02) - a clone of
 *  `use-contacts-list-config.tsx` (the Resource-shell clone source per plan
 *  §2.2), never a hand-rolled table. */
import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { DataGridTableRowSelect, DataGridTableRowSelectAll } from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import type { MigrationJob } from '@/types/respondio-migration';
import type { FilterFieldDef, ListQuery } from '@/types/resource';
import { MIGRATION_MODE_LABEL, MIGRATION_STATUS_REGISTRY, MIGRATION_STATUS_SEGMENTS } from './migration-status';
import { useMigrationActions } from './use-migration-actions';
import { migrationJobPath, migrationNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'spaceLabel', label: 'Source', type: 'text' },
  { field: 'workspaceName', label: 'Target workspace', type: 'text' },
  {
    field: 'mode',
    label: 'Mode',
    type: 'enum',
    options: [
      { label: 'Dry run', value: 'dry_run' },
      { label: 'Migration', value: 'run' },
    ],
  },
  { field: 'createdAt', label: 'Created', type: 'date' },
];

export function useMigrationListConfig(): ResourceListConfig<MigrationJob> {
  const { formatDateTime } = useDatetime();
  const actions = useMigrationActions();
  const router = useRouter();

  return useMemo<ResourceListConfig<MigrationJob>>(() => {
    const columns: ColumnDef<MigrationJob>[] = [
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
        id: 'spaceLabel',
        accessorFn: (row) => row.spaceLabel,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.spaceLabel} lines={1} className="font-medium text-foreground" />,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'workspaceName',
        accessorFn: (row) => row.workspaceName,
        meta: { headerTitle: 'Target workspace' },
        header: ({ column }) => <DataGridColumnHeader title="Target workspace" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.workspaceName} lines={1} />,
        size: 170,
        enableSorting: true,
      },
      {
        id: 'mode',
        accessorFn: (row) => row.mode,
        meta: { headerTitle: 'Mode' },
        header: ({ column }) => <DataGridColumnHeader title="Mode" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{MIGRATION_MODE_LABEL[row.original.mode]}</span>,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => <StatusBadge status={row.original.status} registry={MIGRATION_STATUS_REGISTRY} />,
        size: 130,
        enableSorting: true,
      },
      {
        id: 'progress',
        accessorFn: (row) => (row.progressTotal > 0 ? row.progressDone / row.progressTotal : 0),
        meta: { headerTitle: 'Progress' },
        header: ({ column }) => <DataGridColumnHeader title="Progress" column={column} />,
        cell: ({ row }) => {
          const r = row.original;
          const pct = r.progressTotal > 0 ? Math.round((r.progressDone / r.progressTotal) * 100) : 0;
          return (
            <div className="flex min-w-[120px] items-center gap-2">
              <Progress value={pct} className="h-1.5 w-20" />
              <span className="text-muted-foreground text-xs">{pct}%</span>
            </div>
          );
        },
        size: 150,
        enableSorting: false,
      },
      {
        id: 'contacts',
        accessorFn: (row) => row.entityCounts?.contacts ?? 0,
        meta: { headerTitle: 'Contacts' },
        header: ({ column }) => <DataGridColumnHeader title="Contacts" column={column} />,
        cell: ({ row }) => <span>{row.original.entityCounts?.contacts ?? 0}</span>,
        size: 100,
        enableSorting: false,
      },
      {
        id: 'messages',
        accessorFn: (row) => row.entityCounts?.messages ?? 0,
        meta: { headerTitle: 'Messages' },
        header: ({ column }) => <DataGridColumnHeader title="Messages" column={column} />,
        cell: ({ row }) => <span>{row.original.entityCounts?.messages ?? 0}</span>,
        size: 100,
        enableSorting: false,
      },
      {
        id: 'failures',
        accessorFn: (row) => row.failureCount,
        meta: { headerTitle: 'Failures' },
        header: ({ column }) => <DataGridColumnHeader title="Failures" column={column} />,
        cell: ({ row }) =>
          row.original.failureCount > 0 ? (
            <Badge variant="destructive" appearance="light" size="sm">
              {row.original.failureCount}
            </Badge>
          ) : (
            <span className="text-muted-foreground">0</span>
          ),
        size: 100,
        enableSorting: false,
      },
      {
        id: 'startedAt',
        accessorFn: (row) => row.startedAt,
        meta: { headerTitle: 'Started' },
        header: ({ column }) => <DataGridColumnHeader title="Started" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.startedAt ? formatDateTime(row.original.startedAt) : '-'}</span>,
        size: 170,
        enableSorting: true,
      },
      {
        id: 'finishedAt',
        accessorFn: (row) => row.finishedAt,
        meta: { headerTitle: 'Finished' },
        header: ({ column }) => <DataGridColumnHeader title="Finished" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.finishedAt ? formatDateTime(row.original.finishedAt) : '-'}</span>,
        size: 170,
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
      viewKey: 'omnichannel.migration.list',
      columns,
      getRowId: (row) => row.id,
      rowHref: (row) => migrationJobPath(row.id),
      fetcher: (query: ListQuery) => respondioMigrationService.listJobs(query),
      filterFields: FILTER_FIELDS,
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search migrations…',
      searchHints: ['Source', 'Target workspace'],
      defaultSort: { id: 'createdAt', desc: true },
      enableStatusViews: false,
      segments: MIGRATION_STATUS_SEGMENTS,
      defaultSegment: 'all',
      createLabel: 'New migration',
      onCreate: () => router.push(migrationNewPath),
      createPermission: 'omnichannel_migration.manage',
    };
  }, [actions, formatDateTime, router]);
}
