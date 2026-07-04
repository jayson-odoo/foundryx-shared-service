'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProjectTemplate } from '@/types/ems';
import { toCsv } from '@/lib/csv';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** A template joined with its owning type's name (the wire carries typeId only). */
export type TemplateRow = ProjectTemplate & { typeName: string };

/** Event Templates on the full Resource shell. Catalog is small master data —
 * fetched whole, joined to types client-side, then search/sort/paginated. */
export function useEventTemplatesListConfig(
  onCreate: () => void,
  onEdit: (item: TemplateRow) => void,
): ResourceListConfig<TemplateRow> {
  const { label, labelPlural } = useTerminology();
  const singular = label('project_template');
  const plural = labelPlural('project_template');
  const typeLabel = label('project_type');

  return useMemo<ResourceListConfig<TemplateRow>>(() => {
    const actions: ResourceAction<TemplateRow>[] = [
      {
        id: 'edit',
        label: 'Open & configure flow',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'project_templates.read',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: false, bulk: false },
        permission: 'project_templates.manage',
        confirm: {
          title: `Delete ${singular.toLowerCase()}?`,
          description: 'Templates already used by events can’t be deleted.',
          confirmLabel: 'Delete',
        },
        run: async (rows, runtime) => {
          await emsService.deleteTemplate(rows[0].id);
          runtime.reload();
        },
      },
    ];

    const columns: ColumnDef<TemplateRow>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
        size: 240,
        enableSorting: true,
      },
      {
        id: 'type',
        accessorFn: (r) => r.typeName,
        meta: { headerTitle: typeLabel },
        header: ({ column }) => <DataGridColumnHeader title={typeLabel} column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">
            {row.original.typeName}
          </Badge>
        ),
        size: 180,
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

    const fetcher = async (q: ListQuery): Promise<ListResult<TemplateRow>> => {
      const [templates, types] = await Promise.all([
        emsService.listTemplates({ pageSize: 200 }),
        emsService.listTypes({ pageSize: 200 }),
      ]);
      const typeName = new Map(types.items.map((t) => [t.id, t.name]));
      let rows: TemplateRow[] = templates.items.map((t) => ({
        ...t,
        typeName: typeName.get(t.typeId) ?? '—',
      }));
      if (q.search) {
        const s = q.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.name.toLowerCase().includes(s) ||
            r.typeName.toLowerCase().includes(s) ||
            (r.description ?? '').toLowerCase().includes(s),
        );
      }
      if (q.sort) {
        const key = q.sort.id === 'type' ? 'typeName' : 'name';
        rows = [...rows].sort((a, b) => String(a[key as 'name' | 'typeName']).localeCompare(String(b[key as 'name' | 'typeName'])));
        if (q.sort.desc) rows.reverse();
      }
      const total = rows.length;
      const start = q.page * q.pageSize;
      return { data: rows.slice(start, start + q.pageSize), total, page: q.page };
    };

    const exporter = async (q: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...q, page: 0, pageSize: 10_000 });
      return toCsv(
        ['ID', 'Name', 'Type', 'Description'],
        data.map((r) => [r.id, r.name, r.typeName, r.description ?? '']),
      );
    };

    return {
      viewKey: 'ems.event-templates',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/event-templates/${r.id}`,
      fetcher,
      exporter,
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', typeLabel, 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'event-templates',
      enableStatusViews: false,
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'project_templates.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'type', label: typeLabel },
        { id: 'description', label: 'Description' },
      ],
      actions,
    };
  }, [onCreate, onEdit, singular, plural, typeLabel]);
}
