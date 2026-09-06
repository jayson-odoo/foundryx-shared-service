'use client';

/**
 * Assignment log embedded Resource-shell config (plan 30, AC-RPT-46) - the
 * `workspace-contact-fields-tab.tsx` precedent: a real `ResourceListConfig`
 * (server-paginated, the shell's Columns control), never a hand-rolled
 * table. Read-only (no row actions, no detail route - `rowHref: () => '#'`).
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { AssignmentLogRow, ReportFilters } from '@/types/omnichannel';
import type { ListResult } from '@/types/resource';

export function useAssignmentLogConfig(
  workspaceId: string,
  filters: ReportFilters,
): ResourceListConfig<AssignmentLogRow> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AssignmentLogRow>>(() => {
    const columns: ColumnDef<AssignmentLogRow>[] = [
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Date' },
        header: ({ column }) => <DataGridColumnHeader title="Date" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{formatDateTime(row.original.createdAt)}</span>,
        size: 170,
      },
      {
        id: 'contactName',
        accessorFn: (r) => r.contactName,
        meta: { headerTitle: 'Contact' },
        header: ({ column }) => <DataGridColumnHeader title="Contact" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.contactName} lines={1} className="font-medium" />,
        size: 160,
      },
      {
        id: 'eventType',
        accessorFn: (r) => r.eventType,
        meta: { headerTitle: 'Event' },
        header: ({ column }) => <DataGridColumnHeader title="Event" column={column} />,
        cell: ({ row }) => <span className="text-sm capitalize">{row.original.eventType}</span>,
        size: 110,
      },
      {
        id: 'previousAssigneeName',
        accessorFn: (r) => r.previousAssigneeName ?? '',
        meta: { headerTitle: 'Previous assignee' },
        header: ({ column }) => <DataGridColumnHeader title="Previous assignee" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.previousAssigneeName ?? '-'}</span>,
        size: 160,
      },
      {
        id: 'assignedToName',
        accessorFn: (r) => r.assignedToName ?? '',
        meta: { headerTitle: 'Assigned to' },
        header: ({ column }) => <DataGridColumnHeader title="Assigned to" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.assignedToName ?? '-'}</span>,
        size: 160,
      },
      {
        id: 'source',
        accessorFn: (r) => r.source,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => <span className="text-sm capitalize text-muted-foreground">{row.original.source}</span>,
        size: 100,
      },
      {
        id: 'actorName',
        accessorFn: (r) => r.actorName ?? '',
        meta: { headerTitle: 'Actor' },
        header: ({ column }) => <DataGridColumnHeader title="Actor" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.actorName ?? '-'}</span>,
        size: 140,
      },
    ];

    return {
      viewKey: 'omnichannel.reports.assignments',
      columns,
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher: async (query): Promise<ListResult<AssignmentLogRow>> => {
        const res = await omnichannelReportService.report(workspaceId, 'assignments', {
          ...filters,
          page: query.page,
          pageSize: query.pageSize,
        });
        return { data: res.rows as AssignmentLogRow[], total: res.total ?? res.rows.length, page: res.page ?? query.page };
      },
      filterFields: [],
      exportColumns: [],
      actions: [],
      enableStatusViews: false,
    };
    // `filters` is a fresh object every parent render (the URL-synced hook's
    // return value) - keying off its serialized shape avoids recomputing
    // (and re-fetching) on every render, only on an actual filter change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, JSON.stringify(filters), formatDateTime]);
}
