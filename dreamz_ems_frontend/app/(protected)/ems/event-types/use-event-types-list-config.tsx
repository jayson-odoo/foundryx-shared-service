'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProjectType } from '@/types/ems';
import { toCsv } from '@/lib/csv';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Event Types on the full Resource shell. The catalog is small master data,
 * so the fetcher pulls it whole and applies search/sort/paginate client-side
 * (same adapter as Terminology). */
export function useEventTypesListConfig(
  onCreate: () => void,
  onEdit: (item: ProjectType) => void,
): ResourceListConfig<ProjectType> {
  const pathname = usePathname();
  const { label, labelPlural } = useTerminology();
  const singular = label('project_type');
  const plural = labelPlural('project_type');

  return useMemo<ResourceListConfig<ProjectType>>(() => {
    const actions: ResourceAction<ProjectType>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'project_types.manage',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: false, bulk: false },
        permission: 'project_types.manage',
        confirm: {
          title: `Delete ${singular.toLowerCase()}?`,
          description: 'This removes the type. Templates using it must be moved or deleted first.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          await emsService.deleteType(rows[0].id);
          runtime.reload();
        },
      },
    ];

    const columns: ColumnDef<ProjectType>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
        size: 260,
        enableSorting: true,
      },
      {
        id: 'description',
        accessorFn: (r) => r.description ?? '',
        meta: { headerTitle: 'Description' },
        header: ({ column }) => <DataGridColumnHeader title="Description" column={column} />,
        cell: ({ row }) =>
          row.original.description ? (
            <span className="text-muted-foreground">{row.original.description}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 420,
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

    const fetcher = async (q: ListQuery): Promise<ListResult<ProjectType>> => {
      const { items } = await emsService.listTypes({ pageSize: 200 });
      let rows = items;
      if (q.search) {
        const s = q.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.name.toLowerCase().includes(s) ||
            (r.description ?? '').toLowerCase().includes(s),
        );
      }
      if (q.sort) {
        rows = [...rows].sort((a, b) => a.name.localeCompare(b.name));
        if (q.sort.desc) rows.reverse();
      }
      const total = rows.length;
      const start = q.page * q.pageSize;
      return { data: rows.slice(start, start + q.pageSize), total, page: q.page };
    };

    const exporter = async (q: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...q, page: 0, pageSize: 10_000 });
      return toCsv(['ID', 'Name', 'Description'], data.map((r) => [r.id, r.name, r.description ?? '']));
    };

    return {
      viewKey: 'ems.event-types',
      getRowId: (r) => r.id,
      rowHref: () => pathname,
      fetcher,
      exporter,
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'event-types',
      enableStatusViews: false,
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'project_types.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'description', label: 'Description' },
      ],
      actions,
    };
  }, [pathname, onCreate, onEdit, singular, plural]);
}
