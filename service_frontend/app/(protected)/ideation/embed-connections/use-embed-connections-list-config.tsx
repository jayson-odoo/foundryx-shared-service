'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Link2, PowerOff, RefreshCw, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import { embedConnectionService } from '@/services/embed-connection-service';
import type { EmbedConnectionItem } from '@/types/embed-connection';
import type { Product } from '@/types/ideation';
import { toCsv } from '@/lib/csv';

const MANAGE = 'ideation.triage.manage';
const stop = (e: React.MouseEvent) => e.stopPropagation();

function sortItems(rows: EmbedConnectionItem[], sort: ListQuery['sort']): EmbedConnectionItem[] {
  if (!sort) return rows;
  const val = (i: EmbedConnectionItem): string => {
    switch (sort.id) {
      case 'connectionId':
        return i.connectionId;
      case 'active':
        return String(i.isActive);
      case 'created':
        return i.createdAt ?? '';
      case 'updated':
        return i.updatedAt ?? '';
      default:
        return '';
    }
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

export interface UseEmbedConnectionsListConfigResult {
  config: ResourceListConfig<EmbedConnectionItem>;
}

/**
 * Embed-connections list config (PLAN-ideation-embed-sso §7) on the shared
 * ResourceList - SAME component as the Users / API-keys lists. The connection set
 * per tenant is small, so the fetcher pulls it whole and applies search/sort/
 * paginate client-side (mirrors the API-keys adapter). No detail page
 * (`rowHref` '#'); Add = the create action, and each row exposes Rotate secret,
 * Activate/Deactivate, and hard Delete - the operations the backend CRUD
 * supports. Product ids are resolved to names (never a raw UUID - cursor rule).
 */
export function useEmbedConnectionsListConfig(
  products: Product[],
  handlers: {
    onCreate: () => void;
    onRotate: (item: EmbedConnectionItem) => void;
  },
): UseEmbedConnectionsListConfigResult {
  const { formatDateTime } = useDatetime();
  const { onCreate, onRotate } = handlers;

  const productName = useMemo(() => {
    const byId = new Map(products.map((p) => [p.id, p.name]));
    return (id: string | null) => (id ? (byId.get(id) ?? id) : 'All ideas');
  }, [products]);

  const actions = useMemo<ResourceAction<EmbedConnectionItem>[]>(
    () => [
      {
        id: 'rotate',
        label: 'Rotate secret',
        icon: RefreshCw,
        permission: MANAGE,
        surfaces: { row: true },
        run: (rows) => {
          const [c] = rows;
          if (c) onRotate(c);
        },
      },
      {
        id: 'toggle-active',
        label: (rows) => (rows[0]?.isActive ? 'Deactivate' : 'Activate'),
        icon: PowerOff,
        permission: MANAGE,
        surfaces: { row: true },
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered
        // `ideation_embed_connections.set_active` handler commits it
        // server-side); the payload carries the TARGET state (the toggle's
        // direction is derived from the row's current state at click time,
        // same as the label above).
        deferred: {
          actionKey: 'ideation_embed_connections.set_active',
          entityType: 'ideation_embed_connection',
          payload: (rows) => ({ isActive: !rows[0]?.isActive }),
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: MANAGE,
        surfaces: { row: true },
        // Grace-window deferred action - no confirm, no `run` (the
        // registered `ideation_embed_connections.delete` handler commits it
        // server-side).
        deferred: {
          actionKey: 'ideation_embed_connections.delete',
          entityType: 'ideation_embed_connection',
        },
      },
    ],
    [onRotate],
  );

  const config = useMemo<ResourceListConfig<EmbedConnectionItem>>(() => {
    const columns: ColumnDef<EmbedConnectionItem>[] = [
      {
        id: 'connectionId',
        accessorFn: (r) => r.connectionId,
        meta: { headerTitle: 'Connection' },
        header: ({ column }) => <DataGridColumnHeader title="Connection" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <Link2 className="size-4 text-muted-foreground" />
            <ClampedText text={row.original.connectionId} lines={1} className="font-medium font-mono" />
          </div>
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'origins',
        accessorFn: (r) => r.allowedOrigins.join(', '),
        meta: { headerTitle: 'Allowed origins' },
        header: ({ column }) => <DataGridColumnHeader title="Allowed origins" column={column} />,
        cell: ({ row }) => {
          const origins = row.original.allowedOrigins;
          return origins.length === 0 ? (
            <span className="text-sm text-muted-foreground">None</span>
          ) : (
            <ClampedText
              text={origins.join(', ')}
              lines={1}
              className="font-mono text-sm text-muted-foreground"
            />
          );
        },
        size: 240,
        enableSorting: false,
      },
      {
        id: 'product',
        accessorFn: (r) => productName(r.productId),
        meta: { headerTitle: 'Product scope' },
        header: ({ column }) => <DataGridColumnHeader title="Product scope" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={productName(row.original.productId)} lines={1} className="text-sm" />
        ),
        size: 180,
        enableSorting: false,
      },
      {
        id: 'active',
        accessorFn: (r) => r.isActive,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <Badge variant={row.original.isActive ? 'success' : 'secondary'} appearance="light">
            {row.original.isActive ? 'Active' : 'Inactive'}
          </Badge>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'updated',
        accessorFn: (r) => r.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.updatedAt ? formatDateTime(row.original.updatedAt) : '-'}
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
                getEntityId={(c) => c.connectionId}
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

    const fetcher = async (query: ListQuery): Promise<ListResult<EmbedConnectionItem>> => {
      const all = await embedConnectionService.list();
      let rows = all;
      const search = query.search?.trim().toLowerCase();
      if (search) {
        rows = rows.filter(
          (r) =>
            r.connectionId.toLowerCase().includes(search) ||
            r.allowedOrigins.some((o) => o.toLowerCase().includes(search)),
        );
      }
      rows = sortItems(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Connection', 'Allowed origins', 'Product scope', 'Status', 'Created', 'Updated'],
        data.map((r) => [
          r.connectionId,
          r.allowedOrigins.join(' | '),
          productName(r.productId),
          r.isActive ? 'Active' : 'Inactive',
          r.createdAt ?? '',
          r.updatedAt ?? '',
        ]),
      );
    };

    return {
      viewKey: 'ideation.embed-connections',
      columns,
      getRowId: (c) => c.connectionId,
      rowHref: () => '#', // no detail page
      fetcher,
      exporter,
      filterFields: [],
      exportColumns: [
        { id: 'connectionId', label: 'Connection' },
        { id: 'origins', label: 'Allowed origins' },
        { id: 'product', label: 'Product scope' },
        { id: 'active', label: 'Status' },
        { id: 'updated', label: 'Updated' },
      ],
      actions,
      searchPlaceholder: 'Search connections…',
      searchHints: ['Connection', 'Origin'],
      defaultSort: { id: 'created', desc: true },
      exportFilename: 'embed-connections',
      enableStatusViews: false,
      createLabel: 'Add connection',
      createPermission: MANAGE,
      onCreate,
    };
  }, [actions, onCreate, formatDateTime, productName]);

  return { config };
}
