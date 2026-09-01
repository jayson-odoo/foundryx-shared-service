'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Users as UsersIcon } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { tenantAdminService } from '@/services/tenant-admin-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { TenantListItem } from '@/types/tenant-admin';
import { useTenantActions } from './use-tenant-actions';
import { tenantStatusRegistry } from './tenant-status';
import { tenantFormPath, tenantNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

// Structured filter builder; fields are whitelisted server-side by the tenants
// column map (plan 07 §9). Search covers name/slug/contact/domain.
const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'slug', label: 'Slug', type: 'text' },
  // ARCHIVED is owned by the Active | Archived view toggle, not the filter.
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [
      { label: 'Active', value: 'ACTIVE' },
      { label: 'Suspended', value: 'SUSPENDED' },
    ],
  },
  { field: 'contactEmail', label: 'Contact email', type: 'text' },
  { field: 'created', label: 'Created', type: 'date' },
];

export function useTenantsListConfig(): ResourceListConfig<TenantListItem> {
  const { formatDate } = useDatetime();
  const router = useRouter();
  const actions = useTenantActions();

  return useMemo<ResourceListConfig<TenantListItem>>(() => {
    const columns: ColumnDef<TenantListItem>[] = [
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
        id: 'tenant',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Tenant' },
        header: ({ column }) => <DataGridColumnHeader title="Tenant" column={column} />,
        cell: ({ row }) => (
          <span className="flex items-center gap-2 font-medium text-foreground leading-tight">
            {row.original.name}
            {row.original.isPlatform && (
              <Badge variant="secondary" appearance="light" size="sm">
                Platform
              </Badge>
            )}
          </span>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'slug',
        accessorFn: (row) => row.slug,
        meta: { headerTitle: 'Slug' },
        header: ({ column }) => <DataGridColumnHeader title="Slug" column={column} />,
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">{row.original.slug}</span>
        ),
        size: 160,
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
            registry={tenantStatusRegistry(row.original)}
          />
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'contact',
        accessorFn: (row) => row.contactEmail ?? '',
        meta: { headerTitle: 'Contact' },
        header: ({ column }) => <DataGridColumnHeader title="Contact" column={column} />,
        cell: ({ row }) =>
          row.original.contactEmail ? (
            <div className="flex flex-col leading-tight">
              <span className="text-sm text-foreground">{row.original.contactName ?? '-'}</span>
              <span className="text-xs text-muted-foreground">{row.original.contactEmail}</span>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'users',
        accessorFn: (row) => row.userCount,
        meta: { headerTitle: 'Users' },
        header: ({ column }) => <DataGridColumnHeader title="Users" column={column} />,
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <UsersIcon className="size-3.5" />
            {row.original.userCount}
          </span>
        ),
        size: 100,
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
      viewKey: 'platform.tenants.list',
      columns,
      getRowId: (t) => t.id,
      rowHref: (t) => tenantFormPath(t.id),
      fetcher: (q) => tenantAdminService.list(q),
      exporter: (q, cols, ids) => tenantAdminService.exportCsv(q, cols, ids),
      filterFields: FILTER_FIELDS,
      exportColumns: [
        { id: 'tenant', label: 'Tenant' },
        { id: 'slug', label: 'Slug' },
        { id: 'status', label: 'Status' },
        { id: 'contact', label: 'Contact' },
        { id: 'users', label: 'Users' },
        { id: 'created', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search tenants…',
      searchHints: ['Name', 'Slug', 'Contact', 'Custom domain'],
      defaultSort: { id: 'created', desc: true },
      // Reuses the Users-list segmented control: 'trashed' = soft-archived
      // tenants (plan 07 §4 - archived hidden from the default view).
      statusViewLabels: { active: 'Active', trashed: 'Archived' },
      exportFilename: 'tenants',
      createLabel: 'Add tenant',
      createPermission: 'tenants.create',
      onCreate: () => router.push(tenantNewPath),
    };
  }, [actions, router, formatDate]);
}
