'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Eye, Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { HubCustomer, Option } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';
import { ACTIVE_FILTER, HUB_ACTIVE_REGISTRY, HUB_MANAGE, hubActiveStatus } from '../../components/hub-meta';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function PillsCell({ items }: { items: Option[] }) {
  return (
    <OverflowPills
      items={items}
      keyFor={(o) => o.code}
      renderPill={(o) => (
        <Badge variant="secondary" appearance="light" size="sm">
          {o.name}
        </Badge>
      )}
    />
  );
}

export interface CustomersListOptions {
  hubId: string;
  onCreate: () => void;
  onEdit: (row: HubCustomer) => void;
  onPreview: (row: HubCustomer) => void;
  refreshKey: number;
}

/** The hub's customer companies (embedded list in the Customers tab). */
export function useCustomersListConfig({
  hubId,
  onCreate,
  onEdit,
  onPreview,
  refreshKey,
}: CustomersListOptions): ResourceListConfig<HubCustomer> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<HubCustomer>>(() => {
    const actions: ResourceAction<HubCustomer>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: HUB_MANAGE,
        surfaces: { row: true },
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'preview',
        label: 'Preview',
        icon: Eye,
        surfaces: { row: true },
        run: (rows) => onPreview(rows[0]),
      },
      {
        id: 'remove',
        label: 'Remove',
        icon: Trash2,
        tone: 'destructive',
        permission: HUB_MANAGE,
        surfaces: { row: true },
        deferred: {
          actionKey: 'hub_connector_customers.remove',
          entityType: 'hub_connector_customer',
          payload: () => ({ hubId }),
        },
      },
    ];

    const columns: ColumnDef<HubCustomer>[] = [
      {
        id: 'customerName',
        accessorFn: (r) => r.customerName,
        meta: { headerTitle: 'Customer' },
        header: ({ column }) => <DataGridColumnHeader title="Customer" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.customerName} lines={1} className="font-medium" />,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'customerCode',
        accessorFn: (r) => r.customerCode,
        meta: { headerTitle: 'Code' },
        header: ({ column }) => <DataGridColumnHeader title="Code" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={row.original.customerCode} lines={1} className="font-mono text-sm text-muted-foreground" />
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'locations',
        accessorFn: (r) => r.locations.length,
        meta: { headerTitle: 'Locations' },
        header: ({ column }) => <DataGridColumnHeader title="Locations" column={column} />,
        cell: ({ row }) => <PillsCell items={row.original.locations} />,
        size: 240,
        enableSorting: false,
      },
      {
        id: 'brands',
        accessorFn: (r) => r.brands.length,
        meta: { headerTitle: 'Brands' },
        header: ({ column }) => <DataGridColumnHeader title="Brands" column={column} />,
        cell: ({ row }) => <PillsCell items={row.original.brands} />,
        size: 240,
        enableSorting: false,
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
        size: 110,
        enableSorting: true,
      },
      {
        id: 'updatedAt',
        accessorFn: (r) => r.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDmyDateTime(row.original.updatedAt)}</span>
        ),
        size: 160,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<HubCustomer>> => {
      void refreshKey;
      const res = await hubConnectorService.listCustomers(hubId, query);
      return { data: res.data, total: res.total, page: query.page };
    };

    return {
      // No trash for hub customers: the Active | Trashed switch would mean nothing.
      enableStatusViews: false,
      ...embeddedListConfig<HubCustomer>({
        viewKey: 'hub-connector.customers',
        columns,
        fetcher,
        getRowId: (r) => r.id,
        rowHref: () => '#',
        searchPlaceholder: 'Search customers…',
        defaultSort: { id: 'customerName', desc: false },
        createLabel: 'Create',
        createPermission: HUB_MANAGE,
        onCreate,
        actions,
      }),
      filterFields: [ACTIVE_FILTER],
      onRowSelect: (row) => onEdit(row),
      onDeferredCommitted: () => undefined,
    };
  }, [formatDmyDateTime, hubId, onCreate, onEdit, onPreview, refreshKey]);
}
