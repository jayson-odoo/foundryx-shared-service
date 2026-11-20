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
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { userService } from '@/services/user-service';
import { rolesService } from '@/services/roles-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { FilterFieldDef } from '@/types/resource';
import type { Role, User } from '@/types/user';
import { UserAvatar } from '@/components/platform/user-avatar';
import { RolesCell } from './role-pills';
import { USER_STATUS_REGISTRY } from './user-status';
import { useUserActions } from './use-user-actions';
import { userFormPath, userNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

// Static filter fields; the Role field's options are injected from live roles.
const STATIC_FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'email', label: 'Email', type: 'text' },
  {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [
      { label: 'Active', value: 'ACTIVE' },
      { label: 'Inactive', value: 'INACTIVE' },
      { label: 'Blocked', value: 'BLOCKED' },
      { label: 'Invited', value: 'INVITED' },
    ],
  },
  { field: 'joined', label: 'Joined', type: 'date' },
  { field: 'lastSignIn', label: 'Last Sign In', type: 'date' },
];

export function useUsersListConfig(): ResourceListConfig<User> {
  const { formatDate, formatDateTime } = useDatetime();
  const router = useRouter();
  const actions = useUserActions();
  const [roles, setRoles] = useState<Role[]>([]);

  // Role filter options come from the live (tenant) roles, not a static list.
  useEffect(() => {
    rolesService.list().then(setRoles).catch(() => setRoles([]));
  }, []);

  const filterFields = useMemo<FilterFieldDef[]>(
    () => [
      STATIC_FILTER_FIELDS[0],
      STATIC_FILTER_FIELDS[1],
      {
        field: 'role',
        label: 'Role',
        type: 'enum',
        options: roles.map((r) => ({ label: r.name, value: r.name })),
      },
      ...STATIC_FILTER_FIELDS.slice(2),
    ],
    [roles],
  );

  return useMemo<ResourceListConfig<User>>(() => {
    const columns: ColumnDef<User>[] = [
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
        id: 'user',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'User' },
        header: ({ column }) => <DataGridColumnHeader title="User" column={column} />,
        cell: ({ row }) => {
          const user = row.original;
          return (
            <div className="flex items-center gap-2.5">
              <UserAvatar user={user} size="sm" />
              <div className="flex flex-col min-w-0">
                <ClampedText
                  text={user.name ?? '-'}
                  lines={1}
                  className="font-medium text-foreground leading-tight"
                />
                <ClampedText text={user.email} lines={1} className="text-xs text-muted-foreground" />
              </div>
            </div>
          );
        },
        size: 280,
        enableSorting: true,
      },
      {
        id: 'role',
        accessorFn: (row) => row.roles.map((r) => r.name).join(', '),
        meta: { headerTitle: 'Roles' },
        header: ({ column }) => <DataGridColumnHeader title="Roles" column={column} />,
        cell: ({ row }) => <RolesCell roles={row.original.roles} />,
        size: 220,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={row.original.status} registry={USER_STATUS_REGISTRY} />
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'joined',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Joined' },
        header: ({ column }) => <DataGridColumnHeader title="Joined" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'lastSignIn',
        accessorFn: (row) => row.lastSignInAt,
        meta: { headerTitle: 'Last Sign In' },
        header: ({ column }) => <DataGridColumnHeader title="Last Sign In" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastSignInAt ? formatDateTime(row.original.lastSignInAt) : 'Never'}
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
      viewKey: 'users.list',
      columns,
      getRowId: (u) => u.id,
      rowHref: (u) => userFormPath(u.id),
      fetcher: (q) => userService.list(q),
      exporter: (q, cols, ids) => userService.exportCsv(q, cols, ids),
      filterFields,
      exportColumns: [
        // ID first - the import match key (export → edit → re-import to update).
        { id: 'id', label: 'ID' },
        { id: 'user', label: 'Name' },
        { id: 'email', label: 'Email' },
        { id: 'role', label: 'Roles' },
        { id: 'status', label: 'Status' },
        { id: 'joined', label: 'Joined' },
        { id: 'lastSignIn', label: 'Last Sign In' },
      ],
      actions,
      searchPlaceholder: 'Search users…',
      searchHints: ['Name', 'Email'],
      defaultSort: { id: 'joined', desc: true },
      enableStatusViews: true,
      exportFilename: 'users',
      createLabel: 'Add user',
      createPermission: 'users.create',
      onCreate: () => router.push(userNewPath),
      // Opt-in bulk import (plan sprint-3/09) - the first engine consumer.
      importer: { entityType: 'user', writePermission: 'users.create' },
    };
  }, [actions, router, filterFields, formatDate, formatDateTime]);
}
