'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { useTerminology } from '@/hooks/use-terminology';
import { formService } from '@/services/form-service';
import type { FormRow } from '@/types/forms';
import { FORMS_PATH, formPath } from './paths';
import { useFormActions } from './use-form-actions';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function useFormsListConfig(): ResourceListConfig<FormRow> {
  const router = useRouter();
  const actions = useFormActions();
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  // Relabelable (F10): the create button + search placeholder follow the
  // tenant's word for this entity ("New survey", "Search surveys…").
  const singular = label('form');
  const plural = labelPlural('form');

  return useMemo<ResourceListConfig<FormRow>>(() => {
    const columns: ColumnDef<FormRow>[] = [
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
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">{row.original.name}</span>
            <ClampedText
              text={row.original.description ?? ''}
              lines={1}
              className="text-xs text-muted-foreground"
            />
          </div>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'published',
        accessorFn: (row) => row.currentVersionNumber,
        meta: { headerTitle: 'Published' },
        header: ({ column }) => <DataGridColumnHeader title="Published" column={column} />,
        cell: ({ row }) => {
          const { currentVersionNumber, hasUnpublishedChanges, status } = row.original;
          if (currentVersionNumber == null || status !== 'published') {
            return <span className="text-xs text-muted-foreground">Not published</span>;
          }
          return (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-foreground">v{currentVersionNumber}</span>
              {hasUnpublishedChanges ? (
                <Badge variant="warning" appearance="light" size="sm">
                  Unpublished changes
                </Badge>
              ) : (
                <Badge variant="success" appearance="light" size="sm">
                  Published
                </Badge>
              )}
            </div>
          );
        },
        size: 200,
        enableSorting: true,
      },
      {
        id: 'access',
        accessorFn: (row) => row.access,
        meta: { headerTitle: 'Access' },
        header: ({ column }) => <DataGridColumnHeader title="Access" column={column} />,
        cell: ({ row }) => (
          <Badge
            variant={row.original.access === 'public' ? 'info' : 'secondary'}
            appearance="light"
            size="sm"
          >
            {row.original.access === 'public' ? 'Public' : 'Internal'}
          </Badge>
        ),
        size: 100,
        enableSorting: true,
      },
      {
        id: 'submissionCount',
        accessorFn: (row) => row.submissionCount,
        meta: { headerTitle: 'Submissions' },
        header: ({ column }) => <DataGridColumnHeader title="Submissions" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-foreground">{row.original.submissionCount}</span>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'window',
        accessorFn: (row) => row.opensAt,
        meta: { headerTitle: 'Window' },
        header: ({ column }) => <DataGridColumnHeader title="Window" column={column} />,
        cell: ({ row }) => {
          const { opensAt, closesAt } = row.original;
          if (!opensAt && !closesAt) {
            return <span className="text-xs text-muted-foreground">Always open</span>;
          }
          return (
            <span className="text-xs text-muted-foreground">
              {opensAt ? formatDateTime(opensAt) : '…'} → {closesAt ? formatDateTime(closesAt) : '…'}
            </span>
          );
        },
        size: 220,
        enableSorting: false,
      },
      {
        id: 'updatedAt',
        accessorFn: (row) => row.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDateTime(row.original.updatedAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ reload: meta?.reload ?? (() => {}) }}
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
      viewKey: 'forms',
      getRowId: (row) => row.id,
      rowHref: (row) => formPath(row.id),
      fetcher: (query) => formService.list(query),
      exporter: (query, exportColumns) => formService.export(query, exportColumns),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'forms',
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'forms.manage',
      onCreate: () => router.push(`${FORMS_PATH}/new`),
      statusViewLabels: { active: 'Active', trashed: 'Archived' },
      columns,
      filterFields: [
        { field: 'name', label: 'Name', type: 'text' },
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Draft', value: 'draft' },
            { label: 'Published', value: 'published' },
          ],
        },
        {
          field: 'access',
          label: 'Access',
          type: 'enum',
          options: [
            { label: 'Internal', value: 'internal' },
            { label: 'Public', value: 'public' },
          ],
        },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'slug', label: 'Slug' },
        { id: 'status', label: 'Status' },
        { id: 'access', label: 'Access' },
        { id: 'submissionCount', label: 'Submissions' },
        { id: 'updatedAt', label: 'Updated' },
      ],
      actions,
    };
  }, [actions, router, formatDateTime, singular, plural]);
}
