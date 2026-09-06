'use client';

/**
 * Tags list config (plan 25, AC-CDM-32) - the workspace's tag registry as an
 * embedded ResourceList. Mirrors `use-contact-field-list.tsx` (small
 * per-workspace set, client-side search/sort). No detail page.
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PencilLine, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import type { ContactTag } from '@/types/omnichannel';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface UseContactTagListParams {
  tags: ContactTag[];
  onEdit: (tag: ContactTag) => void;
  onDelete: (tag: ContactTag) => void;
  onAdd: () => void;
}

export interface UseContactTagListResult {
  config: ResourceListConfig<ContactTag>;
}

/** `permission`/`createPermission` are UX-only gates (AC-CDM-33). */
export function useContactTagList({ tags, onEdit, onDelete, onAdd }: UseContactTagListParams): UseContactTagListResult {
  const { formatDate } = useDatetime();

  const actions = useMemo<ResourceAction<ContactTag>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: PencilLine,
        permission: 'contact_tags.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'contact_tags.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onDelete(rows[0]),
      },
    ],
    [onEdit, onDelete],
  );

  const config = useMemo<ResourceListConfig<ContactTag>>(() => {
    const columns: ColumnDef<ContactTag>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            {row.original.emoji && <span aria-hidden>{row.original.emoji}</span>}
            <ClampedText text={row.original.name} lines={1} className="font-medium" />
          </div>
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'color',
        accessorFn: (r) => r.color ?? '',
        meta: { headerTitle: 'Colour' },
        header: ({ column }) => <DataGridColumnHeader title="Colour" column={column} />,
        cell: ({ row }) =>
          row.original.color ? (
            <span className="flex items-center gap-2">
              <span
                className="size-3.5 rounded-full border border-border"
                style={{ backgroundColor: row.original.color }}
              />
              <span className="font-mono text-xs text-muted-foreground uppercase">{row.original.color}</span>
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'description',
        accessorFn: (r) => r.description ?? '',
        meta: { headerTitle: 'Description' },
        header: ({ column }) => <DataGridColumnHeader title="Description" column={column} />,
        cell: ({ row }) =>
          row.original.description ? (
            <ClampedText text={row.original.description} lines={1} className="text-sm text-muted-foreground" />
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'contactsCount',
        accessorFn: (r) => r.contactsCount,
        meta: { headerTitle: 'Contacts' },
        header: ({ column }) => <DataGridColumnHeader title="Contacts" column={column} />,
        cell: ({ row }) => <span className="text-sm tabular-nums">{row.original.contactsCount}</span>,
        size: 100,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Date added' },
        header: ({ column }) => <DataGridColumnHeader title="Date added" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
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

    const fetcher = async (query: ListQuery): Promise<ListResult<ContactTag>> => {
      let rows = [...tags];
      const search = query.search?.trim().toLowerCase();
      if (search) rows = rows.filter((t) => t.name.toLowerCase().includes(search));
      if (query.sort) {
        const { id, desc } = query.sort;
        const val = (t: ContactTag): string | number => {
          switch (id) {
            case 'name':
              return t.name;
            case 'contactsCount':
              return t.contactsCount;
            case 'created':
              return t.createdAt;
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
      viewKey: 'omnichannel.contact-tags',
      columns,
      getRowId: (t) => t.id,
      rowHref: () => '#',
      fetcher,
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search tags…',
      searchHints: ['Name'],
      defaultSort: { id: 'name', desc: false },
      enableStatusViews: false,
      createLabel: 'Create tag',
      createPermission: 'contact_tags.manage',
      onCreate: onAdd,
    };
  }, [tags, actions, onAdd, formatDate]);

  return { config };
}
