'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Ban } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { Planner3dKeyItem } from '@/types/planner3d';
import { useDatetime } from '@/hooks/use-datetime';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { toCsv } from '@/lib/csv';
import { planner3dService } from '@/services/planner3d-service';

export type Planner3dKeyStatus = 'ACTIVE' | 'REVOKED';

export const PLANNER3D_KEY_STATUS: StatusRegistry<Planner3dKeyStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  REVOKED: { label: 'Revoked', tone: 'secondary' },
};

export function planner3dKeyStatus(key: Planner3dKeyItem): Planner3dKeyStatus {
  return key.revokedAt ? 'REVOKED' : 'ACTIVE';
}

const KEYS_MANAGE = 'planner3d.keys.manage';

const spec: ClientListSpec<Planner3dKeyItem> = {
  searchText: (k) => [k.name, k.keyMasked],
  value: (k, field) => {
    switch (field) {
      case 'name':
        return k.name.toLowerCase();
      case 'key':
        return k.keyMasked;
      case 'status':
        return planner3dKeyStatus(k);
      case 'created':
        return k.createdAt;
      case 'lastUsed':
        return k.lastUsedAt;
      default:
        return null;
    }
  },
};

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * 3D Planner keys (lane PLANNER-3D-S1) on the Resource shell, cloned from Lead
 * Capture keys. A tenant holds
 * a handful of keys, so the fetcher loads them whole and `applyClientQuery`
 * searches/filters/sorts/pages. Create = toolbar button; Revoke = grace-window
 * row action (`planner3d_keys.revoke`).
 */
/** `refreshKey`: bump it to refetch (after a Create) without remounting the list,
 *  which would restore the address bar's state from page load. */
export function usePlanner3dKeyList(onCreate: () => void, refreshKey = 0): ResourceListConfig<Planner3dKeyItem> {
  const { formatDmyDateTime } = useDatetime();

  const actions = useMemo<ResourceAction<Planner3dKeyItem>[]>(
    () => [
      {
        id: 'revoke',
        label: 'Revoke',
        icon: Ban,
        tone: 'destructive',
        permission: KEYS_MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && planner3dKeyStatus(rows[0]) === 'ACTIVE',
        deferred: { actionKey: 'planner3d_keys.revoke', entityType: 'planner3d_key' },
      },
    ],
    [],
  );

  return useMemo<ResourceListConfig<Planner3dKeyItem>>(() => {
    const dateCell = (value: string | null) => (
      <span className="text-sm text-muted-foreground">{value ? formatDmyDateTime(value) : '-'}</span>
    );
    const columns: ColumnDef<Planner3dKeyItem>[] = [
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
        id: 'key',
        accessorFn: (r) => r.keyMasked,
        meta: { headerTitle: 'Key' },
        header: ({ column }) => <DataGridColumnHeader title="Key" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={row.original.keyMasked} lines={1} className="font-mono text-sm text-muted-foreground" />
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => dateCell(row.original.createdAt),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'lastUsed',
        accessorFn: (r) => r.lastUsedAt,
        meta: { headerTitle: 'Last used' },
        header: ({ column }) => <DataGridColumnHeader title="Last used" column={column} />,
        cell: ({ row }) => dateCell(row.original.lastUsedAt),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => planner3dKeyStatus(r),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={planner3dKeyStatus(row.original)} registry={PLANNER3D_KEY_STATUS} />
          </div>
        ),
        size: 120,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<Planner3dKeyItem>> => {
      // A new refreshKey = a new fetcher, which the list refetches with its
      // current query (no remount).
      void refreshKey;
      return applyClientQuery(await planner3dService.listKeys(), query, spec);
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Name', 'Key', 'Created', 'Last used', 'Status'],
        data.map((k) => [
          k.name,
          k.keyMasked,
          formatDmyDateTime(k.createdAt),
          k.lastUsedAt ? formatDmyDateTime(k.lastUsedAt) : '-',
          PLANNER3D_KEY_STATUS[planner3dKeyStatus(k)].label,
        ]),
      );
    };

    return {
      viewKey: 'planner3d.keys',
      columns,
      getRowId: (k) => k.id,
      rowHref: () => '#',
      fetcher,
      exporter,
      filterFields: [
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Active', value: 'ACTIVE' },
            { label: 'Revoked', value: 'REVOKED' },
          ],
        },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'key', label: 'Key' },
        { id: 'created', label: 'Created' },
        { id: 'lastUsed', label: 'Last used' },
        { id: 'status', label: 'Status' },
      ],
      actions,
      searchPlaceholder: 'Search keys…',
      defaultSort: { id: 'created', desc: true },
      exportFilename: 'planner3d-keys',
      enableStatusViews: false,
      urlState: true,
      createLabel: 'Create',
      createPermission: KEYS_MANAGE,
      onCreate,
    };
  }, [actions, formatDmyDateTime, onCreate, refreshKey]);
}
