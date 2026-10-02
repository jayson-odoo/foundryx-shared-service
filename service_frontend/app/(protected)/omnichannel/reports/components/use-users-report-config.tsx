'use client';

/**
 * Users / Leaderboard embedded Resource-shell config (plan 30, AC-RPT-46) -
 * ONE config shared by both renderers (`reportKey` picks `users` vs
 * `leaderboard`, `showRank` adds the leaderboard's rank column). Read-only,
 * server-paginated, the shell's Columns control.
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { formatDuration } from '@/lib/duration';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { LeaderboardRow, ReportFilters, ReportKey, UserReportRow } from '@/types/omnichannel';
import type { ListResult } from '@/types/resource';

export function useUsersReportConfig(
  workspaceId: string,
  reportKey: Extract<ReportKey, 'users' | 'leaderboard'>,
  filters: ReportFilters,
  showRank: boolean,
): ResourceListConfig<UserReportRow | LeaderboardRow> {
  return useMemo<ResourceListConfig<UserReportRow | LeaderboardRow>>(() => {
    const columns: ColumnDef<UserReportRow | LeaderboardRow>[] = [
      ...(showRank
        ? ([
            {
              id: 'rank',
              accessorFn: (r) => ('rank' in r ? r.rank : 0),
              meta: { headerTitle: 'Rank' },
              header: ({ column }) => <DataGridColumnHeader title="Rank" column={column} />,
              cell: ({ row }) => <span className="text-sm font-medium">#{'rank' in row.original ? row.original.rank : '-'}</span>,
              size: 70,
              enableHiding: false,
            },
          ] as ColumnDef<UserReportRow | LeaderboardRow>[])
        : []),
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium" />,
        size: 160,
        enableHiding: false,
      },
      {
        id: 'assignedCount',
        accessorFn: (r) => r.assignedCount,
        meta: { headerTitle: 'Assigned' },
        header: ({ column }) => <DataGridColumnHeader title="Assigned" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.assignedCount}</span>,
        size: 100,
      },
      {
        id: 'closedCount',
        accessorFn: (r) => r.closedCount,
        meta: { headerTitle: 'Closed' },
        header: ({ column }) => <DataGridColumnHeader title="Closed" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.closedCount}</span>,
        size: 90,
      },
      {
        id: 'uniqueContacts',
        accessorFn: (r) => r.uniqueContacts,
        meta: { headerTitle: 'Unique contacts' },
        header: ({ column }) => <DataGridColumnHeader title="Unique contacts" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.uniqueContacts}</span>,
        size: 130,
      },
      {
        id: 'messagesSent',
        accessorFn: (r) => r.messagesSent,
        meta: { headerTitle: 'Messages sent' },
        header: ({ column }) => <DataGridColumnHeader title="Messages sent" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.messagesSent}</span>,
        size: 130,
      },
      {
        id: 'commentsCount',
        accessorFn: (r) => r.commentsCount,
        meta: { headerTitle: 'Comments' },
        header: ({ column }) => <DataGridColumnHeader title="Comments" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.commentsCount}</span>,
        size: 100,
      },
      {
        id: 'medianFirstResponseSeconds',
        accessorFn: (r) => r.medianFirstResponseSeconds ?? -1,
        meta: { headerTitle: 'Median first response' },
        header: ({ column }) => <DataGridColumnHeader title="Median first response" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{formatDuration(row.original.medianFirstResponseSeconds)}</span>,
        size: 160,
      },
      {
        id: 'medianResolutionSeconds',
        accessorFn: (r) => r.medianResolutionSeconds ?? -1,
        meta: { headerTitle: 'Median resolution' },
        header: ({ column }) => <DataGridColumnHeader title="Median resolution" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{formatDuration(row.original.medianResolutionSeconds)}</span>,
        size: 150,
      },
    ];

    return {
      viewKey: `omnichannel.reports.${reportKey}`,
      columns,
      getRowId: (r) => r.userId,
      rowHref: () => '#',
      fetcher: async (query): Promise<ListResult<UserReportRow | LeaderboardRow>> => {
        const res = await omnichannelReportService.report(workspaceId, reportKey, {
          ...filters,
          page: query.page,
          pageSize: query.pageSize,
        });
        return {
          data: res.rows as (UserReportRow | LeaderboardRow)[],
          total: res.total ?? res.rows.length,
          page: res.page ?? query.page,
        };
      },
      filterFields: [],
      exportColumns: [],
      actions: [],
      enableStatusViews: false,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, reportKey, JSON.stringify(filters), showRank]);
}
