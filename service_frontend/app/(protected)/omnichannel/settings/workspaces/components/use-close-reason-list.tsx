'use client';

/**
 * Close-reasons list config (plan 27, AC-IVE-31) - the workspace's close-
 * reason registry as an embedded ResourceList, mirroring
 * `use-contact-tag-list.tsx`. Delete is offered only while `usesCount === 0`;
 * otherwise the row offers Deactivate/Activate instead (D-A3-13 - history
 * must keep resolving the reason's name).
 *
 * Delete is a deferred (grace-window) action (review round 1 frontend
 * follow-up, finding 5) - no confirm dialog, a countdown in its place via
 * the registered `close_reasons.delete` handler; `onDeferredCommitted`
 * threads back to the tab's own `refresh()` so the in-memory `reasons` list
 * (not just the shell's `reload()`) picks up the deletion.
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { CircleSlash, PencilLine, Power, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import type { CloseReason } from '@/types/omnichannel';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface UseCloseReasonListParams {
  reasons: CloseReason[];
  canManage: boolean;
  onEdit: (reason: CloseReason) => void;
  onSetActive: (reason: CloseReason, isActive: boolean) => void;
  onAdd: () => void;
  /** Called after a deferred delete commits (review round 1) - refreshes the
   * tab's own `reasons` source. */
  onChanged: () => void;
}

export interface UseCloseReasonListResult {
  config: ResourceListConfig<CloseReason>;
}

export function useCloseReasonList({
  reasons,
  canManage,
  onEdit,
  onSetActive,
  onAdd,
  onChanged,
}: UseCloseReasonListParams): UseCloseReasonListResult {
  const { formatDate } = useDatetime();

  const actions = useMemo<ResourceAction<CloseReason>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: PencilLine,
        permission: 'close_reasons.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onEdit(rows[0]),
      },
      {
        id: 'deactivate',
        label: 'Deactivate',
        icon: CircleSlash,
        permission: 'close_reasons.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && rows[0].isActive,
        run: (rows) => rows[0] && onSetActive(rows[0], false),
      },
      {
        id: 'activate',
        label: 'Activate',
        icon: Power,
        permission: 'close_reasons.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && !rows[0].isActive,
        run: (rows) => rows[0] && onSetActive(rows[0], true),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'close_reasons.manage',
        surfaces: { row: true },
        // Foolproof-UI: a reason with history offers ONLY Deactivate (the
        // real DELETE 409s anyway - this keeps the option off the menu).
        isVisible: (rows) => rows.length === 1 && rows[0].usesCount === 0,
        deferred: { actionKey: 'close_reasons.delete', entityType: 'close_reason' },
      },
    ],
    [onEdit, onSetActive],
  );

  const config = useMemo<ResourceListConfig<CloseReason>>(() => {
    const columns: ColumnDef<CloseReason>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium" />,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'sortOrder',
        accessorFn: (r) => r.sortOrder,
        meta: { headerTitle: 'Sort order' },
        header: ({ column }) => <DataGridColumnHeader title="Sort order" column={column} />,
        cell: ({ row }) => <span className="text-sm tabular-nums">{row.original.sortOrder}</span>,
        size: 100,
        enableSorting: true,
      },
      {
        id: 'isActive',
        accessorFn: (r) => r.isActive,
        meta: { headerTitle: 'Active' },
        header: ({ column }) => <DataGridColumnHeader title="Active" column={column} />,
        cell: ({ row }) =>
          row.original.isActive ? (
            <Badge variant="success" appearance="light" size="sm">
              Active
            </Badge>
          ) : (
            <Badge variant="secondary" appearance="light" size="sm">
              Inactive
            </Badge>
          ),
        size: 100,
        enableSorting: true,
      },
      {
        id: 'usesCount',
        accessorFn: (r) => r.usesCount,
        meta: { headerTitle: 'Uses' },
        header: ({ column }) => <DataGridColumnHeader title="Uses" column={column} />,
        cell: ({ row }) => <span className="text-sm tabular-nums">{row.original.usesCount}</span>,
        size: 90,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Date added' },
        header: ({ column }) => <DataGridColumnHeader title="Date added" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>,
        size: 140,
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
                onDeferredCommitted={onChanged}
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

    const fetcher = async (query: ListQuery): Promise<ListResult<CloseReason>> => {
      let rows = [...reasons];
      const search = query.search?.trim().toLowerCase();
      if (search) rows = rows.filter((r) => r.name.toLowerCase().includes(search));
      if (query.sort) {
        const { id, desc } = query.sort;
        const val = (r: CloseReason): string | number | boolean => {
          switch (id) {
            case 'name':
              return r.name;
            case 'sortOrder':
              return r.sortOrder;
            case 'isActive':
              return r.isActive ? 1 : 0;
            case 'usesCount':
              return r.usesCount;
            case 'created':
              return r.createdAt;
            default:
              return '';
          }
        };
        rows = [...rows].sort((a, b) => {
          const av = val(a);
          const bv = val(b);
          return typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv));
        });
        if (desc) rows.reverse();
      }
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    return {
      viewKey: 'omnichannel.close-reasons',
      columns,
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher,
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search close reasons…',
      searchHints: ['Name'],
      defaultSort: { id: 'sortOrder', desc: false },
      enableStatusViews: false,
      ...(canManage ? { createLabel: 'Create close reason', createPermission: 'close_reasons.manage', onCreate: onAdd } : {}),
    };
  }, [reasons, actions, onAdd, canManage, formatDate, onChanged]);

  return { config };
}
