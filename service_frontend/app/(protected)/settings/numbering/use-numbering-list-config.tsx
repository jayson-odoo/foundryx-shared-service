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
import { numberingService } from '@/services/numbering-service';
import type { NumberCatalogItem, NumberReset } from '@/types/numbering';
import { NUMBER_RESET_OPTIONS } from '@/types/numbering';
import { toCsv } from '@/lib/csv';
import { Pencil, RotateCcw } from 'lucide-react';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const isOverridden = (i: NumberCatalogItem) =>
  i.overridePrefix !== null || i.overrideFormat !== null || i.overrideReset !== null;

const resetLabel = (r: NumberReset) =>
  NUMBER_RESET_OPTIONS.find((o) => o.value === r)?.label ?? r;

/** Walk the (small) catalog client-side for the declared filter fields. */
function matchesFilter(item: NumberCatalogItem, group: FilterGroup | null | undefined): boolean {
  if (!group || group.rules.length === 0) return true;
  const test = (rule: FilterRule): boolean => {
    if (rule.kind === 'group') return matchesGroup(item, rule);
    const v = String(rule.value ?? '').toLowerCase();
    if (rule.field === 'module') {
      const m = item.module.toLowerCase();
      return rule.operator === 'neq' ? m !== v : m.includes(v);
    }
    if (rule.field === 'reset') {
      const r = item.reset.toLowerCase();
      return rule.operator === 'neq' ? r !== v : r === v;
    }
    if (rule.field === 'overridden') {
      return rule.operator === 'is_true' ? isOverridden(item) : !isOverridden(item);
    }
    return true;
  };
  return matchesGroup(item, group, test);
}

function matchesGroup(
  item: NumberCatalogItem,
  group: FilterGroup,
  test?: (r: FilterRule) => boolean,
): boolean {
  const t = test ?? ((r: FilterRule) => matchesFilter(item, { kind: 'group', combinator: 'and', rules: [r] }));
  const results = group.rules.map(t);
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

function sortItems(rows: NumberCatalogItem[], sort: ListQuery['sort']): NumberCatalogItem[] {
  if (!sort) return rows;
  const key = sort.id;
  const val = (i: NumberCatalogItem): string => {
    if (key === 'docType') return i.label;
    if (key === 'prefix') return i.prefix;
    if (key === 'format') return i.formatPattern;
    if (key === 'reset') return i.reset;
    if (key === 'nextVal') return String(i.nextVal).padStart(12, '0');
    return '';
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

/**
 * Numbering list config (sprint-4/07, Cluster F) — the document-numbering
 * catalog on the FULL Resource shell (search · filter · column prefs · sort ·
 * export). The catalog is small client data, so the fetcher pulls it whole and
 * filters/sorts/paginates client-side. Edit is an inline dialog (no detail page).
 */
export function useNumberingListConfig(
  onEdit: (item: NumberCatalogItem) => void,
): ResourceListConfig<NumberCatalogItem> {
  const pathname = usePathname();

  return useMemo<ResourceListConfig<NumberCatalogItem>>(() => {
    const actions: ResourceAction<NumberCatalogItem>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'numbering.manage',
        run: (rows) => onEdit(rows[0]),
      },
      {
        id: 'reset',
        label: 'Reset to default',
        icon: RotateCcw,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'numbering.manage',
        isDisabled: (rows) => !rows.some(isOverridden),
        run: async (rows, runtime) => {
          await numberingService.resetFormat(rows[0].docType);
          runtime.reload();
        },
      },
    ];

    const columns: ColumnDef<NumberCatalogItem>[] = [
      {
        id: 'docType',
        accessorFn: (r) => r.label,
        meta: { headerTitle: 'Document type' },
        header: ({ column }) => <DataGridColumnHeader title="Document type" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">{row.original.label}</span>
            <span className="text-xs text-muted-foreground">{row.original.docType}</span>
          </div>
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'prefix',
        accessorFn: (r) => r.prefix,
        meta: { headerTitle: 'Prefix' },
        header: ({ column }) => <DataGridColumnHeader title="Prefix" column={column} />,
        cell: ({ row }) =>
          row.original.prefix ? (
            <span className="font-mono text-sm">{row.original.prefix}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'format',
        accessorFn: (r) => r.formatPattern,
        meta: { headerTitle: 'Format' },
        header: ({ column }) => <DataGridColumnHeader title="Format" column={column} />,
        cell: ({ row }) => (
          <span className="font-mono text-sm text-muted-foreground">{row.original.formatPattern}</span>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'reset',
        accessorFn: (r) => r.reset,
        meta: { headerTitle: 'Reset' },
        header: ({ column }) => <DataGridColumnHeader title="Reset" column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">
            {resetLabel(row.original.reset)}
          </Badge>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'nextVal',
        accessorFn: (r) => r.nextVal,
        meta: { headerTitle: 'Next value' },
        header: ({ column }) => <DataGridColumnHeader title="Next value" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-medium tabular-nums">{row.original.nextVal}</span>
            <span className="font-mono text-xs text-muted-foreground">{row.original.sample}</span>
            {isOverridden(row.original) && (
              <Badge variant="primary" appearance="light" size="sm">
                Custom
              </Badge>
            )}
          </div>
        ),
        size: 240,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<NumberCatalogItem>> => {
      const all = await numberingService.getCatalog();
      let rows = all;
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.docType.toLowerCase().includes(s) ||
            r.label.toLowerCase().includes(s) ||
            r.prefix.toLowerCase().includes(s) ||
            r.formatPattern.toLowerCase().includes(s),
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
        ['Document type', 'Key', 'Module', 'Prefix', 'Format', 'Reset', 'Next value'],
        data.map((r) => [r.label, r.docType, r.module, r.prefix, r.formatPattern, r.reset, String(r.nextVal)]),
      );
    };

    return {
      viewKey: 'numbering',
      getRowId: (row) => row.docType,
      rowHref: () => pathname, // no detail page — edit is an inline action
      fetcher,
      exporter,
      searchPlaceholder: 'Search document types…',
      searchHints: ['Type', 'Prefix', 'Format'],
      defaultSort: { id: 'docType', desc: false },
      exportFilename: 'numbering',
      enableStatusViews: false,
      columns,
      filterFields: [
        { field: 'module', label: 'Module', type: 'text' },
        {
          field: 'reset',
          label: 'Reset',
          type: 'enum',
          options: NUMBER_RESET_OPTIONS,
        },
        { field: 'overridden', label: 'Customised', type: 'bool' },
      ],
      exportColumns: [
        { id: 'docType', label: 'Document type' },
        { id: 'prefix', label: 'Prefix' },
        { id: 'format', label: 'Format' },
        { id: 'reset', label: 'Reset' },
        { id: 'nextVal', label: 'Next value' },
      ],
      actions,
    };
  }, [onEdit, pathname]);
}
