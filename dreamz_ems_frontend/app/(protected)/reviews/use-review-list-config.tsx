'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { csvEscape } from '@/lib/csv';
import { reviewConfigService } from '@/services/review-config-service';
import type { ReviewConfig } from '@/types/review';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface ReviewListConfigCtx {
  onCreate: () => void;
  onEdit: (row: ReviewConfig) => void;
  onDelete: (row: ReviewConfig) => Promise<void>;
}

/** "Review processes" on the full Resource shell — search · sort · column prefs ·
 * select · export. Each row is a `review_configuration` over a (submission form,
 * review form) pair. Create/Open/Delete in the row + bulk "…". */
export function useReviewListConfig(ctx: ReviewListConfigCtx): ResourceListConfig<ReviewConfig> {
  const { onCreate, onEdit, onDelete } = ctx;
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<ReviewConfig>>(() => {
    const editAction: ResourceAction<ReviewConfig> = {
      id: 'edit',
      label: 'Open',
      icon: Pencil,
      surfaces: { row: true, form: false, bulk: false },
      permission: 'reviews.read',
      run: ([row]) => {
        if (row) onEdit(row);
      },
    };

    const deleteAction: ResourceAction<ReviewConfig> = {
      id: 'delete',
      label: 'Delete',
      icon: Trash2,
      tone: 'destructive',
      surfaces: { row: true, form: false, bulk: true },
      permission: 'reviews.manage',
      confirm: {
        title: 'Delete review process?',
        description: 'This removes the configuration and its roles. Submissions are not deleted.',
        confirmLabel: 'Delete',
      },
      run: async (rows, rt) => {
        let ok = 0;
        for (const r of rows) {
          try {
            await onDelete(r);
            ok += 1;
          } catch {
            /* counted as skipped */
          }
        }
        const skipped = rows.length - ok;
        if (ok === 0) toast.error('Could not delete.');
        else if (skipped > 0) toast.warning(`${ok} deleted, ${skipped} skipped.`);
        else toast.success(`${ok} deleted.`);
        rt?.reload?.();
      },
    };

    const rowMenuActions = [editAction, deleteAction];

    const columns: ColumnDef<ReviewConfig>[] = [
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
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
        size: 260,
        enableSorting: true,
      },
      {
        id: 'formId',
        accessorFn: (r) => r.formId,
        meta: { headerTitle: 'Submission form' },
        header: ({ column }) => <DataGridColumnHeader title="Submission form" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground font-mono text-xs">{row.original.formId}</span>
        ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'reviewFormId',
        accessorFn: (r) => r.reviewFormId,
        meta: { headerTitle: 'Review form' },
        header: ({ column }) => <DataGridColumnHeader title="Review form" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground font-mono text-xs">{row.original.reviewFormId}</span>
        ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'requiredReviewCount',
        accessorFn: (r) => r.requiredReviewCount,
        meta: { headerTitle: 'Required reviews' },
        header: ({ column }) => <DataGridColumnHeader title="Required reviews" column={column} />,
        cell: ({ row }) => <span>{row.original.requiredReviewCount}</span>,
        size: 140,
        enableSorting: true,
      },
      {
        id: 'window',
        accessorFn: (r) => r.windowStart ?? '',
        meta: { headerTitle: 'Window' },
        header: ({ column }) => <DataGridColumnHeader title="Window" column={column} />,
        cell: ({ row }) => {
          const { windowStart, windowEnd } = row.original;
          if (!windowStart && !windowEnd) {
            return <span className="text-muted-foreground">—</span>;
          }
          return (
            <span className="text-muted-foreground text-xs">
              {windowStart ? formatDateTime(windowStart) : '—'} →{' '}
              {windowEnd ? formatDateTime(windowEnd) : '—'}
            </span>
          );
        },
        size: 220,
        enableSorting: false,
      },
      {
        id: 'isActive',
        accessorFn: (r) => (r.isActive ? 'Active' : 'Inactive'),
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
        size: 110,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={rowMenuActions}
                rows={[row.original]}
                runtime={{ reload }}
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

    return {
      viewKey: 'reviews.configurations',
      getRowId: (r) => r.id,
      rowHref: (r) => `/reviews/${r.id}`,
      fetcher: (q) => reviewConfigService.list(q),
      exporter: async (q, cols) => {
        const all = await reviewConfigService.list({ ...q, page: 0, pageSize: 10_000 });
        const header = cols.join(',');
        const rows = all.data.map((r) =>
          cols
            .map((c) => csvEscape(String((r as unknown as Record<string, unknown>)[c] ?? '')))
            .join(','),
        );
        return [header, ...rows].join('\n');
      },
      searchPlaceholder: 'Search review processes…',
      searchHints: ['Name'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'review-processes',
      enableStatusViews: false,
      createLabel: 'New review process',
      createPermission: 'reviews.manage',
      onCreate,
      columns,
      actions: [deleteAction],
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'formId', label: 'Submission form' },
        { id: 'reviewFormId', label: 'Review form' },
        { id: 'requiredReviewCount', label: 'Required reviews' },
      ],
    };
  }, [formatDateTime, onCreate, onEdit, onDelete]);
}
