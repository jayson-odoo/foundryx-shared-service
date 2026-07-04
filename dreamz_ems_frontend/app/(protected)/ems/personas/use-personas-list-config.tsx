'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Lock, Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { personaService } from '@/services/persona-service';
import type { Persona } from '@/types/persona';
import { toCsv } from '@/lib/csv';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * Personas on the full Resource shell (AC-06-26). The catalog is small tenant
 * config, so the fetcher pulls it whole and applies search/sort/paginate
 * client-side (same adapter as Event Types / Terminology). System personas are
 * delete-locked; the row Delete action hides for them (the server also 409s).
 */
export function usePersonasListConfig(
  onCreate: () => void,
  onEdit: (item: Persona) => void,
): ResourceListConfig<Persona> {
  const pathname = usePathname();

  return useMemo<ResourceListConfig<Persona>>(() => {
    const actions: ResourceAction<Persona>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'personas.manage',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: false, bulk: false },
        permission: 'personas.manage',
        // System personas are delete-locked (server 409s); hide the action.
        isVisible: (rows) => rows.length > 0 && !rows[0].isSystem,
        confirm: {
          title: 'Delete persona?',
          description:
            'This removes the persona. Profiles holding it lose its portal access.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          await personaService.remove(rows[0].id);
          runtime.reload();
        },
      },
    ];

    const columns: ColumnDef<Persona>[] = [
      {
        id: 'label',
        accessorFn: (r) => r.label,
        meta: { headerTitle: 'Label' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Label" column={column} />
        ),
        cell: ({ row }) => (
          <span className="font-medium">{row.original.label}</span>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'key',
        accessorFn: (r) => r.key,
        meta: { headerTitle: 'Key' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Key" column={column} />
        ),
        cell: ({ row }) => (
          <code className="text-xs text-muted-foreground">{row.original.key}</code>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'system',
        accessorFn: (r) => (r.isSystem ? 'System' : 'Custom'),
        meta: { headerTitle: 'Type' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Type" column={column} />
        ),
        cell: ({ row }) =>
          row.original.isSystem ? (
            <Badge variant="secondary" appearance="light" size="sm">
              <Lock className="size-3" /> System
            </Badge>
          ) : (
            <Badge variant="primary" appearance="light" size="sm">
              Custom
            </Badge>
          ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'description',
        accessorFn: (r) => r.description ?? '',
        meta: { headerTitle: 'Description' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Description" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.description || '—'}
          </span>
        ),
        size: 360,
        enableSorting: false,
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

    const fetcher = async (q: ListQuery): Promise<ListResult<Persona>> => {
      const items = await personaService.list();
      let rows = items;
      if (q.search) {
        const s = q.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.label.toLowerCase().includes(s) ||
            r.key.toLowerCase().includes(s) ||
            (r.description ?? '').toLowerCase().includes(s),
        );
      }
      rows = [...rows].sort((a, b) => a.sortOrder - b.sortOrder);
      if (q.sort) {
        rows = [...rows].sort((a, b) => {
          const key = q.sort!.id === 'key' ? 'key' : 'label';
          return a[key].localeCompare(b[key]);
        });
        if (q.sort.desc) rows.reverse();
      }
      const total = rows.length;
      const start = q.page * q.pageSize;
      return { data: rows.slice(start, start + q.pageSize), total, page: q.page };
    };

    const exporter = async (q: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...q, page: 0, pageSize: 10_000 });
      return toCsv(
        ['ID', 'Key', 'Label', 'System', 'Description'],
        data.map((r) => [
          r.id,
          r.key,
          r.label,
          r.isSystem ? 'yes' : 'no',
          r.description ?? '',
        ]),
      );
    };

    return {
      viewKey: 'ems.personas',
      getRowId: (r) => r.id,
      rowHref: () => pathname,
      fetcher,
      exporter,
      searchPlaceholder: 'Search personas…',
      searchHints: ['Label', 'Key', 'Description'],
      defaultSort: { id: 'label', desc: false },
      exportFilename: 'personas',
      enableStatusViews: false,
      createLabel: 'New persona',
      createPermission: 'personas.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'key', label: 'Key' },
        { id: 'label', label: 'Label' },
        { id: 'system', label: 'System' },
        { id: 'description', label: 'Description' },
      ],
      actions,
    };
  }, [pathname, onCreate, onEdit]);
}
