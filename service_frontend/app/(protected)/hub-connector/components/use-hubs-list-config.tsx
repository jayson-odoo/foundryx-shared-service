'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { Hub } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';
import { HUB_ACTIVE_REGISTRY, HUB_MANAGE, hubActiveStatus, hubHref } from './hub-meta';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Deletes a hub (grace window; backend registry key `hub_connector_hubs.delete`). */
export const HUB_DELETE_ACTION: ResourceAction<Hub> = {
  id: 'delete',
  label: 'Delete',
  icon: Trash2,
  tone: 'destructive',
  permission: HUB_MANAGE,
  surfaces: { row: true, form: true },
  deferred: { actionKey: 'hub_connector_hubs.delete', entityType: 'hub_connector_hub' },
};

/**
 * Hubs list on the Resource shell: server-side search, sort and paging
 * (`GET /hub-connector/hubs`). A new refreshKey refetches without a remount.
 */
export function useHubsListConfig(onCreate: () => void, refreshKey = 0): ResourceListConfig<Hub> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<Hub>>(() => {
    const actions = [HUB_DELETE_ACTION];
    const columns: ColumnDef<Hub>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium" />,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'code',
        accessorFn: (r) => r.code,
        meta: { headerTitle: 'Code' },
        header: ({ column }) => <DataGridColumnHeader title="Code" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={row.original.code} lines={1} className="font-mono text-sm text-muted-foreground" />
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'callbackUrl',
        accessorFn: (r) => r.callbackUrl,
        meta: { headerTitle: 'Receiver URL' },
        header: ({ column }) => <DataGridColumnHeader title="Receiver URL" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={row.original.callbackUrl} lines={1} className="text-sm text-muted-foreground" />
        ),
        size: 260,
        enableSorting: true,
      },
      {
        id: 'exposePrice',
        accessorFn: (r) => r.exposePrice,
        meta: { headerTitle: 'Show price' },
        header: ({ column }) => <DataGridColumnHeader title="Show price" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.exposePrice ? 'Yes' : 'No'}</span>,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'customerCount',
        accessorFn: (r) => r.customerCount,
        meta: { headerTitle: 'Customers' },
        header: ({ column }) => <DataGridColumnHeader title="Customers" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.customerCount}</span>,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'active',
        accessorFn: (r) => r.active,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={hubActiveStatus(row.original.active)} registry={HUB_ACTIVE_REGISTRY} />
          </div>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'lastSuccessAt',
        accessorFn: (r) => r.lastSuccessAt,
        meta: { headerTitle: 'Last delivered' },
        header: ({ column }) => <DataGridColumnHeader title="Last delivered" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastSuccessAt ? formatDmyDateTime(row.original.lastSuccessAt) : '-'}
          </span>
        ),
        size: 170,
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
                runtime={{
                  ctx: meta?.resourceCtx,
                  index: (meta?.pageStartIndex ?? 0) + row.index,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<Hub>> => {
      void refreshKey;
      const res = await hubConnectorService.listHubs(query);
      return { data: res.data, total: res.total, page: query.page };
    };

    return {
      viewKey: 'hub-connector.hubs',
      columns,
      getRowId: (h) => h.id,
      rowHref: (h) => hubHref(h.id),
      fetcher,
      filterFields: [],
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search hubs…',
      defaultSort: { id: 'name', desc: false },
      enableStatusViews: false,
      urlState: true,
      createLabel: 'Create',
      createPermission: HUB_MANAGE,
      onCreate,
      pageTitle: 'Hubs',
    };
  }, [formatDmyDateTime, onCreate, refreshKey]);
}
