'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { leadCaptureSourcesService } from '@/services/lead-capture-sources-service';
import type { StaffLead, StaffSource } from '@/types/lead-capture-sources';
import type { FilterFieldDef } from '@/types/resource';
import { DELIVERY_STATUS_REGISTRY, PLATFORM_LABELS } from '../../sources/components/source-status';

function text(id: keyof StaffLead, title: string, size: number): ColumnDef<StaffLead> {
  return {
    id,
    accessorFn: (r) => r[id],
    meta: { headerTitle: title },
    header: ({ column }) => <DataGridColumnHeader title={title} column={column} />,
    cell: ({ row }) => <ClampedText text={String(row.original[id] ?? '-')} lines={1} className="text-sm" />,
    size,
    enableSorting: true,
  };
}

export function useLeadsListConfig(sourceId: string | null): ResourceListConfig<StaffLead> {
  const { formatDmyDateTime } = useDatetime();
  const [sources, setSources] = useState<StaffSource[]>([]);

  useEffect(() => {
    leadCaptureSourcesService
      .listSources({ page: 0, pageSize: 200 })
      .then((r) => setSources(r.data))
      .catch(() => setSources([]));
  }, []);

  return useMemo<ResourceListConfig<StaffLead>>(() => {
    const filterFields: FilterFieldDef[] = [
      {
        field: 'source',
        label: 'Source',
        type: 'enum',
        operators: ['in'],
        options: sources.map((s) => ({ value: s.id, label: s.name })),
      },
      {
        field: 'platform',
        label: 'Channel',
        type: 'enum',
        operators: ['in'],
        options: Object.entries(PLATFORM_LABELS).map(([value, label]) => ({ value, label })),
      },
      { field: 'receivedAt', label: 'Received', type: 'date' },
      { field: 'isTest', label: 'Test lead', type: 'bool' },
    ];

    const columns: ColumnDef<StaffLead>[] = [
      {
        id: 'receivedAt',
        accessorFn: (r) => r.receivedAt,
        meta: { headerTitle: 'Received' },
        header: ({ column }) => <DataGridColumnHeader title="Received" column={column} />,
        cell: ({ row }) => <span className="text-sm">{formatDmyDateTime(row.original.receivedAt)}</span>,
        size: 180,
        enableSorting: true,
      },
      { ...text('name', 'Name', 200), enableSorting: false },
      text('email', 'Email', 220),
      text('phone', 'Phone', 160),
      text('sourceName', 'Source', 200),
      text('formName', 'Form', 200),
      {
        id: 'platform',
        accessorFn: (r) => r.platform,
        meta: { headerTitle: 'Channel' },
        header: ({ column }) => <DataGridColumnHeader title="Channel" column={column} />,
        cell: ({ row }) => <span className="text-sm">{PLATFORM_LABELS[row.original.platform] ?? row.original.platform}</span>,
        size: 120,
        enableSorting: true,
      },
      {
        id: 'isTest',
        accessorFn: (r) => r.isTest,
        meta: { headerTitle: 'Test lead' },
        header: ({ column }) => <DataGridColumnHeader title="Test lead" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.isTest ? 'Yes' : 'No'}</span>,
        size: 110,
        enableSorting: true,
      },
      {
        id: 'deliveryStatus',
        accessorFn: (r) => r.deliveryStatus,
        meta: { headerTitle: 'Delivery' },
        header: ({ column }) => <DataGridColumnHeader title="Delivery" column={column} />,
        cell: ({ row }) =>
          row.original.deliveryStatus ? (
            <StatusBadge status={row.original.deliveryStatus} registry={DELIVERY_STATUS_REGISTRY} />
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 130,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'lead-capture.leads',
      pageTitle: 'Leads',
      columns,
      getRowId: (r) => r.id,
      rowHref: (r) => `/lead-capture/leads/${encodeURIComponent(r.id)}`,
      fetcher: (q) => leadCaptureSourcesService.listLeads(q, sourceId),
      filterFields,
      exportColumns: [],
      actions: [],
      searchPlaceholder: 'Search email, phone, form or source',
      defaultSort: { id: 'receivedAt', desc: true },
    };
  }, [formatDmyDateTime, sourceId, sources]);
}
