'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { toCsv } from '@/lib/csv';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { BusinessRequirement } from '@/types/business-requirement';
import { brFormHref } from './components/paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface BrListHandlers {
  onCreate: () => void;
  onDelete: (br: BusinessRequirement) => Promise<void>;
}

/**
 * Business Requirements list config on the shared ResourceList (SAME component as
 * Users / Ideas - never a hand-rolled table). Client-side fetcher over the loaded
 * BRs; row-click opens the detail form. Active | Archived status views; the only
 * bulk/row action in S2 is Delete (lifecycle status moves live on the detail).
 */
export function useBrListConfig(
  brs: BusinessRequirement[],
  handlers: BrListHandlers,
): ResourceListConfig<BusinessRequirement> {
  const { onCreate, onDelete } = handlers;

  return useMemo<ResourceListConfig<BusinessRequirement>>(() => {
    const actions: ResourceAction<BusinessRequirement>[] = [
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, form: true, bulk: true },
        confirm: {
          title: 'Delete business requirement',
          description:
            'This permanently removes the BR and its idea links. This action cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows) => {
          for (const r of rows) await onDelete(r);
        },
      },
    ];

    const columns: ColumnDef<BusinessRequirement>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'title',
        header: () => 'Title',
        cell: ({ row }) => (
          <ClampedText text={row.original.title || 'Untitled BR'} lines={2} />
        ),
        size: 320,
        enableSorting: false,
      },
      {
        id: 'product',
        header: () => 'Product',
        cell: ({ row }) => <Badge variant="secondary">{row.original.productName}</Badge>,
        size: 150,
        enableSorting: false,
      },
      {
        id: 'status',
        header: () => 'Status',
        cell: ({ row }) => (
          <Badge variant="outline" appearance="light">
            {row.original.statusLabel}
          </Badge>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'ideas',
        header: () => 'Ideas',
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.ideaCount}</span>
        ),
        size: 80,
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
        size: 56,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (
      query: ListQuery,
    ): Promise<ListResult<BusinessRequirement>> => {
      const archivedView = query.statusView === 'trashed';
      let rows = brs.filter((r) =>
        archivedView ? r.status === 'archived' : r.status !== 'archived',
      );
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            r.title.toLowerCase().includes(s) ||
            r.productName.toLowerCase().includes(s),
        );
      }
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Title', 'Product', 'Status', 'Ideas'],
        data.map((r) => [r.title, r.productName, r.statusLabel, String(r.ideaCount)]),
      );
    };

    return {
      viewKey: 'ideation.business_requirements',
      getRowId: (row) => row.id,
      rowHref: (row) => brFormHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search business requirements…',
      searchHints: ['Title', 'Product'],
      enableStatusViews: true,
      statusViewLabels: { active: 'Active', trashed: 'Archived' },
      createLabel: 'New requirement',
      createPermission: 'ideation.business_requirements.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'title', label: 'Title' },
        { id: 'product', label: 'Product' },
        { id: 'status', label: 'Status' },
      ],
      actions,
    };
  }, [brs, onCreate, onDelete]);
}
