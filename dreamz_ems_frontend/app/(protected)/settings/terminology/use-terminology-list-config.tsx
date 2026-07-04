'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult, FilterGroup, FilterRule } from '@/types/resource';
import { refreshTerminology } from '@/hooks/use-terminology';
import { terminologyService } from '@/services/terminology-service';
import type { TermCatalogItem } from '@/types/terminology';
import { toCsv } from '@/lib/csv';
import { Pencil, RotateCcw } from 'lucide-react';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const isOverridden = (i: TermCatalogItem) =>
  i.overrideSingular !== null || i.overridePlural !== null;

/** Walk the (small) catalog client-side for the declared filter fields. */
function matchesFilter(item: TermCatalogItem, group: FilterGroup | null | undefined): boolean {
  if (!group || group.rules.length === 0) return true;
  const test = (rule: FilterRule): boolean => {
    if (rule.kind === 'group') return matchesGroup(item, rule);
    const v = String(rule.value ?? '').toLowerCase();
    if (rule.field === 'group') {
      const g = (item.group ?? '').toLowerCase();
      if (rule.operator === 'eq') return g === v;
      if (rule.operator === 'neq') return g !== v;
      return g.includes(v); // contains
    }
    if (rule.field === 'overridden') {
      return rule.operator === 'is_true' ? isOverridden(item) : !isOverridden(item);
    }
    if (rule.field === 'module') {
      const m = item.module.toLowerCase();
      return rule.operator === 'neq' ? m !== v : m.includes(v);
    }
    return true;
  };
  return matchesGroup(item, group, test);
}

function matchesGroup(
  item: TermCatalogItem,
  group: FilterGroup,
  test?: (r: FilterRule) => boolean,
): boolean {
  const t = test ?? ((r: FilterRule) => matchesFilter(item, { kind: 'group', combinator: 'and', rules: [r] }));
  const results = group.rules.map(t);
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

function sortItems(rows: TermCatalogItem[], sort: ListQuery['sort']): TermCatalogItem[] {
  if (!sort) return rows;
  const key = sort.id;
  const val = (i: TermCatalogItem): string => {
    if (key === 'entity') return i.singular;
    if (key === 'group') return i.group ?? '';
    if (key === 'default') return i.defaultSingular;
    if (key === 'current') return i.singular;
    return '';
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

/**
 * Terminology list config (sprint-3/08, F10) — the catalog on the FULL Resource
 * shell: search, the filter builder, column visibility/reorder/resize (per-user
 * via `viewKey`), sortable columns, and CSV export. The catalog is small client
 * data, so the fetcher pulls it whole and applies search/filter/sort/paginate
 * client-side (the shell is otherwise identical to a server-paginated list).
 */
export function useTerminologyListConfig(
  onEdit: (item: TermCatalogItem) => void,
): ResourceListConfig<TermCatalogItem> {
  const pathname = usePathname();

  return useMemo<ResourceListConfig<TermCatalogItem>>(() => {
    const actions: ResourceAction<TermCatalogItem>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'terminology.manage',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'reset',
        label: 'Reset to default',
        icon: RotateCcw,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'terminology.manage',
        isDisabled: (rows) => !rows.some(isOverridden),
        run: async (rows, runtime) => {
          await terminologyService.resetTerm(rows[0].key);
          await refreshTerminology();
          runtime.reload();
        },
      },
    ];

    const columns: ColumnDef<TermCatalogItem>[] = [
      {
        id: 'entity',
        accessorFn: (r) => r.singular,
        meta: { headerTitle: 'Entity' },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">{row.original.singular}</span>
            <span className="text-xs text-muted-foreground">{row.original.key}</span>
          </div>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'group',
        accessorFn: (r) => r.group ?? '',
        meta: { headerTitle: 'Group' },
        header: ({ column }) => <DataGridColumnHeader title="Group" column={column} />,
        cell: ({ row }) =>
          row.original.group ? (
            <Badge variant="secondary" appearance="light" size="sm">
              {row.original.group}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'default',
        accessorFn: (r) => r.defaultSingular,
        meta: { headerTitle: 'Default' },
        header: ({ column }) => <DataGridColumnHeader title="Default" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.defaultSingular} / {row.original.defaultPlural}
          </span>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'current',
        accessorFn: (r) => r.singular,
        meta: { headerTitle: 'Current label' },
        header: ({ column }) => <DataGridColumnHeader title="Current label" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-medium">
              {row.original.singular} / {row.original.plural}
            </span>
            {isOverridden(row.original) && (
              <Badge variant="primary" appearance="light" size="sm">
                Renamed
              </Badge>
            )}
          </div>
        ),
        size: 260,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<TermCatalogItem>> => {
      const all = await terminologyService.getCatalog();
      let rows = all;
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.key.toLowerCase().includes(s) ||
            r.singular.toLowerCase().includes(s) ||
            r.plural.toLowerCase().includes(s) ||
            (r.group ?? '').toLowerCase().includes(s),
        );
      }
      rows = rows.filter((r) => matchesFilter(r, query.filter));
      rows = sortItems(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Entity key', 'Group', 'Default singular', 'Default plural', 'Current singular', 'Current plural'],
        data.map((r) => [r.key, r.group ?? '', r.defaultSingular, r.defaultPlural, r.singular, r.plural]),
      );
    };

    return {
      viewKey: 'terminology',
      getRowId: (row) => row.key,
      rowHref: () => pathname, // no detail page — edit is an inline action
      fetcher,
      exporter,
      searchPlaceholder: 'Search terminology…',
      searchHints: ['Entity', 'Group', 'Label'],
      defaultSort: { id: 'group', desc: false },
      exportFilename: 'terminology',
      enableStatusViews: false,
      columns,
      filterFields: [
        { field: 'group', label: 'Group', type: 'text' },
        { field: 'module', label: 'Module', type: 'text' },
        {
          field: 'overridden',
          label: 'Renamed',
          type: 'bool',
        },
      ],
      exportColumns: [
        { id: 'key', label: 'Entity key' },
        { id: 'group', label: 'Group' },
        { id: 'default', label: 'Default' },
        { id: 'current', label: 'Current label' },
      ],
      actions,
    };
  }, [onEdit, pathname]);
}
