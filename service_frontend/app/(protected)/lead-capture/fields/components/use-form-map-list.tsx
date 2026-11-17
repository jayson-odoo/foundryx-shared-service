'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { toCsv } from '@/lib/csv';
import { formMapRows, type FormMapRow } from '@/lib/lead-field-map';
import { leadCaptureService } from '@/services/lead-capture-service';

export const FORM_MAP_STATUS: StatusRegistry<FormMapRow['status']> = {
  NEEDS_MAPPING: { label: 'Needs mapping', tone: 'warning' },
  MAPPED: { label: 'Mapped', tone: 'success' },
};

const spec: ClientListSpec<FormMapRow> = {
  searchText: (r) => [r.pageName, r.formName],
  value: (r, field) => {
    switch (field) {
      case 'page':
        return r.pageName.toLowerCase();
      case 'form':
        return r.formName.toLowerCase();
      case 'mapped':
        return r.mappedCount;
      case 'unmapped':
        return r.unmappedCount;
      case 'status':
        return r.status;
      default:
        return null;
    }
  },
};

/**
 * Form maps (lane L-D, AC-64-57): one row per (Page, form) the company knows -
 * forms with a map and forms with a "Map fields" notice. A row click opens the
 * Map fields popup; Create adds a form by its Instant Form id.
 */
export function useFormMapList(
  onOpen: (row: FormMapRow) => void,
  onCreate: () => void,
): ResourceListConfig<FormMapRow> {
  return useMemo<ResourceListConfig<FormMapRow>>(() => {
    const columns: ColumnDef<FormMapRow>[] = [
      {
        id: 'page',
        accessorFn: (r) => r.pageName,
        meta: { headerTitle: 'Page' },
        header: ({ column }) => <DataGridColumnHeader title="Page" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.pageName} lines={1} />,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'form',
        accessorFn: (r) => r.formName,
        meta: { headerTitle: 'Form' },
        header: ({ column }) => <DataGridColumnHeader title="Form" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.formName} lines={1} className="font-medium" />,
        size: 260,
        enableSorting: true,
      },
      {
        id: 'mapped',
        accessorFn: (r) => r.mappedCount,
        meta: { headerTitle: 'Mapped questions' },
        header: ({ column }) => <DataGridColumnHeader title="Mapped questions" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.mappedCount}</span>,
        size: 160,
        enableSorting: true,
      },
      {
        id: 'unmapped',
        accessorFn: (r) => r.unmappedCount,
        meta: { headerTitle: 'Answers in notes' },
        header: ({ column }) => <DataGridColumnHeader title="Answers in notes" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm">{row.original.unmappedCount === null ? '-' : row.original.unmappedCount}</span>
        ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={row.original.status} registry={FORM_MAP_STATUS} />
          </div>
        ),
        size: 150,
        enableSorting: true,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<FormMapRow>> =>
      applyClientQuery(formMapRows(await leadCaptureService.listSources()), query, spec);

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Page', 'Form', 'Mapped questions', 'Answers in notes', 'Status'],
        data.map((r) => [
          r.pageName,
          r.formName,
          String(r.mappedCount),
          r.unmappedCount === null ? '-' : String(r.unmappedCount),
          FORM_MAP_STATUS[r.status].label,
        ]),
      );
    };

    return {
      viewKey: 'lead-capture.form-maps',
      columns,
      getRowId: (r) => r.id,
      rowHref: () => '#',
      onRowSelect: (row) => onOpen(row),
      fetcher,
      exporter,
      filterFields: [
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Needs mapping', value: 'NEEDS_MAPPING' },
            { label: 'Mapped', value: 'MAPPED' },
          ],
        },
      ],
      exportColumns: [
        { id: 'page', label: 'Page' },
        { id: 'form', label: 'Form' },
        { id: 'mapped', label: 'Mapped questions' },
        { id: 'unmapped', label: 'Answers in notes' },
        { id: 'status', label: 'Status' },
      ],
      actions: [],
      searchPlaceholder: 'Search forms…',
      defaultSort: { id: 'status', desc: true },
      exportFilename: 'lead-capture-form-maps',
      enableStatusViews: false,
      createLabel: 'Create',
      createPermission: 'lead_capture.manage',
      onCreate,
    };
  }, [onOpen, onCreate]);
}
