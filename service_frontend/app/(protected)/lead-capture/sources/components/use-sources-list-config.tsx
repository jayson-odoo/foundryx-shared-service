'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Link2, RefreshCw } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { leadCaptureSourcesService } from '@/services/lead-capture-sources-service';
import type { StaffSource } from '@/types/lead-capture-sources';
import type { FilterFieldDef } from '@/types/resource';
import { PLATFORM_LABELS, SOURCE_STATUS_REGISTRY } from './source-status';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    operators: ['in'],
    options: Object.entries(SOURCE_STATUS_REGISTRY).map(([value, meta]) => ({ value, label: meta.label })),
  },
  {
    field: 'platform',
    label: 'Channel',
    type: 'enum',
    operators: ['in'],
    options: Object.entries(PLATFORM_LABELS).map(([value, label]) => ({ value, label })),
  },
];

const ROUTING = new Set(['WAITING_FOR_TEST', 'LIVE']);

export function useSourcesListConfig(openWizard: (sourceId?: string) => void): ResourceListConfig<StaffSource> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<StaffSource>>(() => {
    const actions: ResourceAction<StaffSource>[] = [
      {
        id: 'reconnect',
        label: 'Reconnect',
        icon: RefreshCw,
        surfaces: { row: true },
        permission: 'lead_capture.manage',
        isVisible: (rows) => rows.every((r) => !ROUTING.has(r.status)),
        run: (rows) => openWizard(rows[0].id),
      },
      {
        id: 'map-fields',
        label: 'Map fields',
        icon: Link2,
        surfaces: { row: true },
        permission: 'lead_capture.manage',
        isVisible: (rows) => rows.every((r) => ROUTING.has(r.status) && r.needsMapping.length > 0),
        run: (rows) => openWizard(rows[0].id),
      },
    ];

    const columns: ColumnDef<StaffSource>[] = [
      {
        id: 'platform',
        accessorFn: (r) => r.platform,
        meta: { headerTitle: 'Channel' },
        header: ({ column }) => <DataGridColumnHeader title="Channel" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-foreground">{PLATFORM_LABELS[row.original.platform] ?? row.original.platform}</span>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium text-foreground" />,
        size: 240,
        enableSorting: true,
      },
      {
        id: 'pageName',
        accessorFn: (r) => r.pageName,
        meta: { headerTitle: 'Account' },
        header: ({ column }) => <DataGridColumnHeader title="Account" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.pageName ?? '-'} lines={1} className="text-sm" />,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => <StatusBadge status={row.original.status} registry={SOURCE_STATUS_REGISTRY} />,
        size: 150,
        enableSorting: true,
      },
      {
        id: 'needsMapping',
        accessorFn: (r) => r.needsMapping.length,
        meta: { headerTitle: 'Unmapped forms' },
        header: ({ column }) => <DataGridColumnHeader title="Unmapped forms" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.needsMapping.length || '-'}</span>,
        size: 140,
        enableSorting: false,
      },
      {
        id: 'leads7d',
        accessorFn: (r) => r.leads7d,
        meta: { headerTitle: 'Leads (7 days)' },
        header: ({ column }) => <DataGridColumnHeader title="Leads (7 days)" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.leads7d}</span>,
        size: 130,
        enableSorting: true,
      },
      {
        id: 'lastLeadAt',
        accessorFn: (r) => r.lastLeadAt,
        meta: { headerTitle: 'Last lead' },
        header: ({ column }) => <DataGridColumnHeader title="Last lead" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastLeadAt ? formatDmyDateTime(row.original.lastLeadAt) : '-'}
          </span>
        ),
        size: 180,
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
                runtime={{ ctx: meta?.resourceCtx, index: row.index, reload: meta?.reload ?? (() => {}) }}
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
      viewKey: 'lead-capture.sources',
      pageTitle: 'Sources',
      columns,
      getRowId: (r) => r.id,
      rowHref: (r) => `/lead-capture/leads?source=${encodeURIComponent(r.id)}`,
      fetcher: (q) => leadCaptureSourcesService.listSources(q),
      filterFields: FILTER_FIELDS,
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search sources',
      defaultSort: { id: 'createdAt', desc: true },
      createLabel: 'Connect a source',
      createPermission: 'lead_capture.manage',
      onCreate: () => openWizard(),
    };
  }, [formatDmyDateTime, openWizard]);
}
