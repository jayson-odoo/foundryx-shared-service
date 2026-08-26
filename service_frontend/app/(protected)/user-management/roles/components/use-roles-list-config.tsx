'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { roleService } from '@/services/role-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { RoleListItem } from '@/types/role';
import { useRoleActions } from './use-role-actions';
import { RoleUsersCell } from './role-users-cell';
import { roleFormPath, roleNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

// Structured filter builder; fields are whitelisted server-side by the role
// column map in role_service. (Search box still covers name/desc/user/permission.)
const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'description', label: 'Description', type: 'text' },
  { field: 'system', label: 'System role', type: 'bool' },
  { field: 'created', label: 'Created', type: 'date' },
];

export function useRolesListConfig(): ResourceListConfig<RoleListItem> {
  const { formatDate } = useDatetime();
  const router = useRouter();
  const actions = useRoleActions();

  return useMemo<ResourceListConfig<RoleListItem>>(() => {
    const columns: ColumnDef<RoleListItem>[] = [
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
        id: 'role',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Role' },
        header: ({ column }) => <DataGridColumnHeader title="Role" column={column} />,
        cell: ({ row }) => (
          <span className="flex items-center gap-2 font-medium text-foreground leading-tight">
            {row.original.name}
            {row.original.isSystem && (
              <Badge variant="secondary" appearance="light" size="sm">
                System
              </Badge>
            )}
          </span>
        ),
        size: 260,
        enableSorting: true,
      },
      {
        id: 'description',
        accessorFn: (row) => row.description ?? '',
        meta: { headerTitle: 'Description' },
        header: ({ column }) => <DataGridColumnHeader title="Description" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.description ?? '-'}</span>
        ),
        size: 360,
        enableSorting: false,
      },
      {
        id: 'users',
        accessorFn: (row) => row.userCount,
        meta: { headerTitle: 'Users' },
        header: ({ column }) => <DataGridColumnHeader title="Users" column={column} />,
        cell: ({ row }) => <RoleUsersCell roleId={row.original.id} count={row.original.userCount} />,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'permissions',
        accessorFn: (row) => row.permissionCount,
        meta: { headerTitle: 'Permissions' },
        header: ({ column }) => <DataGridColumnHeader title="Permissions" column={column} />,
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <KeyRound className="size-3.5" />
            {row.original.permissionCount}
          </span>
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
      viewKey: 'roles.list',
      columns,
      getRowId: (r) => r.id,
      rowHref: (r) => roleFormPath(r.id),
      fetcher: (q) => roleService.list(q),
      exporter: (q, cols, ids) => roleService.exportCsv(q, cols, ids),
      filterFields: FILTER_FIELDS,
      exportColumns: [
        { id: 'role', label: 'Role' },
        { id: 'description', label: 'Description' },
        { id: 'users', label: 'Users' },
        { id: 'permissions', label: 'Permissions' },
        { id: 'created', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search roles…',
      searchHints: ['Role name', 'Description', 'Assigned users', 'Permissions'],
      defaultSort: { id: 'created', desc: true },
      enableStatusViews: false,
      exportFilename: 'roles',
      createLabel: 'Add role',
      createPermission: 'roles.create',
      onCreate: () => router.push(roleNewPath),
    };
  }, [actions, router, formatDate]);
}
