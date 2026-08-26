'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { QuickReply } from '@/types/omnichannel';
import { toCsv } from '@/lib/csv';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function sortRows(rows: QuickReply[], sort: ListQuery['sort']): QuickReply[] {
  if (!sort) return rows;
  const val = (r: QuickReply): string =>
    sort.id === 'body' ? r.body : (r.shortcut ?? '');
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

/**
 * Quick-replies list config (plan sprint-3/12) - canned responses on the FULL
 * Resource shell (search · column visibility/reorder/resize · sort · export).
 * The dataset is small workspace-scoped client data: `items` is supplied by the
 * page's `useQuickReplies` hook and the fetcher pages over it client-side (the
 * same client-adapter pattern as the terminology list). Edit/Delete/Create are
 * inline actions - no detail page.
 */
export function useQuickRepliesListConfig(
  items: QuickReply[],
  handlers: {
    onCreate: () => void;
    onEdit: (item: QuickReply) => void;
    onDelete: (item: QuickReply) => Promise<void>;
  },
): ResourceListConfig<QuickReply> {
  const pathname = usePathname();
  const { onCreate, onEdit, onDelete } = handlers;

  return useMemo<ResourceListConfig<QuickReply>>(() => {
    const actions: ResourceAction<QuickReply>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'workspaces.manage',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: false, bulk: false },
        permission: 'workspaces.manage',
        confirm: {
          title: 'Delete quick reply?',
          description: 'Agents will no longer be able to insert this canned response.',
          confirmLabel: 'Delete',
        },
        run: async (rows) => {
          await onDelete(rows[0]);
        },
      },
    ];

    const columns: ColumnDef<QuickReply>[] = [
      {
        id: 'shortcut',
        accessorFn: (r) => r.shortcut ?? '',
        meta: { headerTitle: 'Shortcut' },
        header: ({ column }) => <DataGridColumnHeader title="Shortcut" column={column} />,
        cell: ({ row }) =>
          row.original.shortcut ? (
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
              {row.original.shortcut}
            </code>
          ) : (
            <span className="text-muted-foreground">-</span>
          ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'body',
        accessorFn: (r) => r.body,
        meta: { headerTitle: 'Message' },
        header: ({ column }) => <DataGridColumnHeader title="Message" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.body} lines={2} />,
        size: 520,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stop} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<QuickReply>> => {
      let rows = items;
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            (r.shortcut ?? '').toLowerCase().includes(s) ||
            r.body.toLowerCase().includes(s),
        );
      }
      rows = sortRows(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Shortcut', 'Message'],
        data.map((r) => [r.shortcut ?? '', r.body]),
      );
    };

    return {
      viewKey: 'omnichannel.quick-replies',
      getRowId: (row) => row.id,
      rowHref: () => pathname, // no detail page - edit is an inline action
      fetcher,
      exporter,
      searchPlaceholder: 'Search quick replies…',
      searchHints: ['Shortcut', 'Message'],
      defaultSort: { id: 'shortcut', desc: false },
      exportFilename: 'quick-replies',
      enableStatusViews: false,
      createLabel: 'New quick reply',
      createPermission: 'workspaces.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'shortcut', label: 'Shortcut' },
        { id: 'body', label: 'Message' },
      ],
      actions,
    };
  }, [items, onCreate, onEdit, onDelete, pathname]);
}
