'use client';

/**
 * Contact-fields list config (plan 25, AC-CDM-31) - the workspace's field
 * registry on the full Resource shell, embedded in the workspace detail form.
 * The set is small per workspace, so the fetcher pulls it whole and applies
 * search/sort client-side (mirrors the API-keys tab adapter). No detail page.
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { PencilLine, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import type { ContactField } from '@/types/omnichannel';
import { CONTACT_FIELD_TYPE_OPTIONS, CONTACT_FIELD_VISIBILITY_OPTIONS } from './contact-field-schema';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const TYPE_LABEL = new Map(CONTACT_FIELD_TYPE_OPTIONS.map((o) => [o.value, o.label]));
const VISIBILITY_LABEL = new Map(CONTACT_FIELD_VISIBILITY_OPTIONS.map((o) => [o.value, o.label]));

export interface UseContactFieldListParams {
  fields: ContactField[];
  onEdit: (field: ContactField) => void;
  onDelete: (field: ContactField) => void;
  onAdd: () => void;
}

export interface UseContactFieldListResult {
  config: ResourceListConfig<ContactField>;
}

/**
 * Note (AC-CDM-33): `permission`/`createPermission` are UX-only gates (as
 * everywhere in the Resource shell) - a user without `contact_fields.manage`
 * sees the tab with no Add/Edit/Delete controls; the API is the real gate.
 */
export function useContactFieldList({
  fields,
  onEdit,
  onDelete,
  onAdd,
}: UseContactFieldListParams): UseContactFieldListResult {
  const { formatDate } = useDatetime();

  const actions = useMemo<ResourceAction<ContactField>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: PencilLine,
        permission: 'contact_fields.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'contact_fields.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onDelete(rows[0]),
      },
    ],
    [onEdit, onDelete],
  );

  const config = useMemo<ResourceListConfig<ContactField>>(() => {
    const columns: ColumnDef<ContactField>[] = [
      {
        id: 'label',
        accessorFn: (r) => r.label,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.label} lines={1} className="font-medium" />,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'key',
        accessorFn: (r) => r.key,
        meta: { headerTitle: 'Field ID' },
        header: ({ column }) => <DataGridColumnHeader title="Field ID" column={column} />,
        cell: ({ row }) => (
          <span className="font-mono text-sm text-muted-foreground">{row.original.key}</span>
        ),
        size: 160,
        enableSorting: true,
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
        id: 'type',
        accessorFn: (r) => r.type,
        meta: { headerTitle: 'Type' },
        header: ({ column }) => <DataGridColumnHeader title="Type" column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">
            {TYPE_LABEL.get(row.original.type) ?? row.original.type}
          </Badge>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'visibility',
        accessorFn: (r) => r.visibility,
        meta: { headerTitle: 'Visibility' },
        header: ({ column }) => <DataGridColumnHeader title="Visibility" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {VISIBILITY_LABEL.get(row.original.visibility) ?? row.original.visibility}
          </span>
        ),
        size: 180,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<ContactField>> => {
      let rows = [...fields].sort((a, b) => a.sortOrder - b.sortOrder);
      const search = query.search?.trim().toLowerCase();
      if (search) {
        rows = rows.filter(
          (f) => f.label.toLowerCase().includes(search) || f.key.toLowerCase().includes(search),
        );
      }
      if (query.sort) {
        const { id, desc } = query.sort;
        const val = (f: ContactField): string => {
          switch (id) {
            case 'label':
              return f.label;
            case 'key':
              return f.key;
            case 'type':
              return f.type;
            case 'visibility':
              return f.visibility;
            case 'created':
              return f.createdAt;
            default:
              return '';
          }
        };
        rows = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
        if (desc) rows.reverse();
      }
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    return {
      viewKey: 'omnichannel.contact-fields',
      columns,
      getRowId: (f) => f.id,
      rowHref: () => '#',
      fetcher,
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions,
      searchPlaceholder: 'Search fields…',
      searchHints: ['Name', 'Field ID'],
      defaultSort: { id: 'created', desc: false },
      enableStatusViews: false,
      createLabel: 'Add custom field',
      createPermission: 'contact_fields.manage',
      onCreate: onAdd,
    };
  }, [fields, actions, onAdd, formatDate]);

  return { config };
}
