'use client';

/** Client apps list config (the "Client apps" settings screen) - a small,
 * tenant-scoped set, client-side search/sort over the whole GET response. */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { FolderInput, PencilLine } from 'lucide-react';
import type { ClientApp } from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { CLIENT_APP_STATUS_REGISTRY } from './client-app-status';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface UseClientAppListParams {
  apps: ClientApp[];
  onRename: (app: ClientApp) => void;
  onViewWorkspaces: (app: ClientApp) => void;
  onAdd: () => void;
}

export interface UseClientAppListResult {
  config: ResourceListConfig<ClientApp>;
}

export function useClientAppList({
  apps,
  onRename,
  onViewWorkspaces,
  onAdd,
}: UseClientAppListParams): UseClientAppListResult {
  const actions = useMemo<ResourceAction<ClientApp>[]>(
    () => [
      {
        id: 'rename',
        label: 'Rename',
        icon: PencilLine,
        permission: 'partner_keys.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onRename(rows[0]),
      },
      {
        id: 'workspaces',
        label: 'Workspaces',
        icon: FolderInput,
        permission: 'partner_keys.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onViewWorkspaces(rows[0]),
      },
    ],
    [onRename, onViewWorkspaces],
  );

  const config = useMemo<ResourceListConfig<ClientApp>>(() => {
    const columns: ColumnDef<ClientApp>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Name" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <ClampedText
              text={row.original.name}
              lines={1}
              className="font-medium"
            />
            {row.original.isDefault && (
              <Badge variant="secondary" appearance="light" size="sm">
                Default
              </Badge>
            )}
          </div>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Status" column={column} />
        ),
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.status}
            registry={CLIENT_APP_STATUS_REGISTRY}
          />
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'workspaceCount',
        accessorFn: (r) => r.workspaceCount,
        meta: { headerTitle: 'Workspaces' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Workspaces" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm tabular-nums">
            {row.original.workspaceCount}
          </span>
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
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{
                  ctx: meta?.resourceCtx,
                  index,
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

    const fetcher = async (
      query: ListQuery,
    ): Promise<ListResult<ClientApp>> => {
      let rows = [...apps];
      const search = query.search?.trim().toLowerCase();
      if (search)
        rows = rows.filter((a) => a.name.toLowerCase().includes(search));
      if (query.sort) {
        const { id, desc } = query.sort;
        const val = (a: ClientApp): string | number => {
          switch (id) {
            case 'name':
              return a.name;
            case 'status':
              return a.status;
            case 'workspaceCount':
              return a.workspaceCount;
            default:
              return '';
          }
        };
        rows = [...rows].sort((a, b) => {
          const av = val(a);
          const bv = val(b);
          return typeof av === 'number' && typeof bv === 'number'
            ? av - bv
            : String(av).localeCompare(String(bv));
        });
        if (desc) rows.reverse();
      }
      const total = rows.length;
      const start = query.page * query.pageSize;
      return {
        data: rows.slice(start, start + query.pageSize),
        total,
        page: query.page,
      };
    };

    return {
      viewKey: 'omnichannel.client-apps',
      columns,
      getRowId: (a) => a.id,
      rowHref: () => '#',
      fetcher,
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search client apps…',
      searchHints: ['Name'],
      defaultSort: { id: 'name', desc: false },
      enableStatusViews: false,
      createLabel: 'Create client app',
      createPermission: 'partner_keys.manage',
      onCreate: onAdd,
    };
  }, [apps, actions, onAdd]);

  return { config };
}
