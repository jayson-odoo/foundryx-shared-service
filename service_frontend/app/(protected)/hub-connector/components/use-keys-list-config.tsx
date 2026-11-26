'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Ban } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { useDatetime } from '@/hooks/use-datetime';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { ApiKey } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';
import { HUB_KEYS_MANAGE } from './hub-meta';

type KeyStatus = 'ACTIVE' | 'REVOKED';

const KEY_STATUS: StatusRegistry<KeyStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  REVOKED: { label: 'Revoked', tone: 'secondary' },
};

export const keyStatus = (k: ApiKey): KeyStatus => (k.revokedAt ? 'REVOKED' : 'ACTIVE');

const spec: ClientListSpec<ApiKey> = {
  searchText: (k) => [k.name, k.masked],
  value: (k, field) => {
    switch (field) {
      case 'name':
        return k.name.toLowerCase();
      case 'masked':
        return k.masked;
      case 'created':
        return k.createdAt;
      case 'lastUsed':
        return k.lastUsedAt;
      case 'status':
        return keyStatus(k);
      default:
        return null;
    }
  },
};

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * Hub keys inside the hub's keys dialog. A company holds a handful, so the fetcher
 * loads them whole and `applyClientQuery` searches/sorts/pages. Revoke is a
 * grace-window action (backend registry key `hub_connector_keys.revoke`).
 */
export function useKeysListConfig(hubId: string, onCreate: () => void, refreshKey: number): ResourceListConfig<ApiKey> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<ApiKey>>(() => {
    const actions: ResourceAction<ApiKey>[] = [
      {
        id: 'revoke',
        label: 'Revoke',
        icon: Ban,
        tone: 'destructive',
        permission: HUB_KEYS_MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && keyStatus(rows[0]) === 'ACTIVE',
        deferred: { actionKey: 'hub_connector_keys.revoke', entityType: 'hub_connector_key' },
      },
    ];
    const dateCell = (v: string | null) => (
      <span className="text-sm text-muted-foreground">{v ? formatDmyDateTime(v) : '-'}</span>
    );
    const columns: ColumnDef<ApiKey>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium" />,
        size: 180,
        enableSorting: true,
      },
      {
        id: 'masked',
        accessorFn: (r) => r.masked,
        meta: { headerTitle: 'Key' },
        header: ({ column }) => <DataGridColumnHeader title="Key" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.masked} lines={1} className="font-mono text-sm" />,
        size: 180,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => dateCell(row.original.createdAt),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'lastUsed',
        accessorFn: (r) => r.lastUsedAt,
        meta: { headerTitle: 'Last used' },
        header: ({ column }) => <DataGridColumnHeader title="Last used" column={column} />,
        cell: ({ row }) => dateCell(row.original.lastUsedAt),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => keyStatus(r),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={keyStatus(row.original)} registry={KEY_STATUS} />
          </div>
        ),
        size: 110,
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
    const fetcher = async (query: ListQuery): Promise<ListResult<ApiKey>> => {
      void refreshKey;
      return applyClientQuery(await hubConnectorService.listKeys(hubId), query, spec);
    };
    return {
      enableStatusViews: false,
      ...embeddedListConfig<ApiKey>({
        viewKey: 'hub-connector.keys',
        columns,
        fetcher,
        getRowId: (k) => k.id,
        rowHref: () => '#',
        searchPlaceholder: 'Search keys…',
        defaultSort: { id: 'created', desc: true },
        createLabel: 'Create',
        createPermission: HUB_KEYS_MANAGE,
        onCreate,
        actions,
      }),
    };
  }, [formatDmyDateTime, hubId, onCreate, refreshKey]);
}
