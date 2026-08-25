'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { MEETING_STATUS_REGISTRY } from '@/components/platform/meeting-status';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { MeetingsBotRun } from '@/types/meetings';
import { toCsv } from '@/lib/csv';
import { formatDateTime } from '@/lib/datetime';

/** Seconds as the operator reads a call length: `58m 12s`, `1h 02m`. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function sortRows(rows: MeetingsBotRun[], sort: ListQuery['sort']): MeetingsBotRun[] {
  if (!sort) return rows;
  const val = (r: MeetingsBotRun): string => {
    switch (sort.id) {
      case 'meeting':
        return r.meetingTitle ?? '';
      case 'ended':
        return r.endedAt ?? '';
      case 'reason':
        return r.exitReason ?? '';
      case 'duration':
        // Numeric, so pad rather than compare "9" against "10" as text.
        return String(r.durationS ?? -1).padStart(9, '0');
      default:
        return r.startedAt ?? r.startsAt;
    }
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

/**
 * Bot-runs list config (S2 plan §6, AC-S2-12).
 *
 * A week of runs is a handful of rows already in memory from
 * `useMeetingsBotRuns`, so the fetcher pages over them client-side — the same
 * client-adapter shape the upcoming-events list uses. There is no detail page:
 * the exit reason IS the detail, and it is on the row.
 */
export function useBotRunsListConfig(
  items: MeetingsBotRun[],
  handlers: { timeZone: string | null },
): ResourceListConfig<MeetingsBotRun> {
  const pathname = usePathname();
  const { timeZone } = handlers;

  return useMemo<ResourceListConfig<MeetingsBotRun>>(() => {
    const when = (iso: string | null): string => formatDateTime(iso, { timeZone });

    const columns: ColumnDef<MeetingsBotRun>[] = [
      {
        id: 'meeting',
        accessorFn: (r) => r.meetingTitle ?? '',
        meta: { headerTitle: 'Meeting' },
        header: ({ column }) => <DataGridColumnHeader title="Meeting" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.meetingTitle ?? '—'} lines={2} />,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'started',
        accessorFn: (r) => r.startedAt ?? r.startsAt,
        meta: { headerTitle: 'Started' },
        header: ({ column }) => <DataGridColumnHeader title="Started" column={column} />,
        // Queued but not yet started is a real state; show the scheduled start
        // rather than a blank cell that reads as missing data.
        cell: ({ row }) => when(row.original.startedAt ?? row.original.startsAt),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'ended',
        accessorFn: (r) => r.endedAt ?? '',
        meta: { headerTitle: 'Ended' },
        header: ({ column }) => <DataGridColumnHeader title="Ended" column={column} />,
        cell: ({ row }) => when(row.original.endedAt),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'reason',
        accessorFn: (r) => r.exitReason ?? '',
        meta: { headerTitle: 'Exit reason' },
        header: ({ column }) => <DataGridColumnHeader title="Exit reason" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge
              status={row.original.meetingStatus}
              registry={MEETING_STATUS_REGISTRY}
              size="sm"
            />
            {row.original.exitReason && (
              <span className="text-xs text-muted-foreground">
                <ClampedText text={row.original.exitReason} lines={2} />
              </span>
            )}
          </div>
        ),
        size: 190,
        enableSorting: true,
      },
      {
        id: 'duration',
        accessorFn: (r) => r.durationS ?? -1,
        meta: { headerTitle: 'Duration' },
        header: ({ column }) => <DataGridColumnHeader title="Duration" column={column} />,
        cell: ({ row }) => formatDuration(row.original.durationS),
        size: 110,
        enableSorting: true,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<MeetingsBotRun>> => {
      let rows = items;
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            (r.meetingTitle ?? '').toLowerCase().includes(s) ||
            (r.exitReason ?? '').toLowerCase().includes(s),
        );
      }
      rows = sortRows(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Meeting', 'Started', 'Ended', 'Status', 'Exit reason', 'Duration'],
        data.map((r) => [
          r.meetingTitle ?? '',
          when(r.startedAt ?? r.startsAt),
          when(r.endedAt),
          MEETING_STATUS_REGISTRY[r.meetingStatus]?.label ?? r.meetingStatus,
          r.exitReason ?? '',
          formatDuration(r.durationS),
        ]),
      );
    };

    // Card view at 375px — the grid would have to scroll sideways to reach the
    // exit reason, which is the only thing anyone opens this list for.
    const cardRender = (row: MeetingsBotRun) => (
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <span className="text-sm font-medium">
            <ClampedText text={row.meetingTitle ?? '—'} lines={2} />
          </span>
          <StatusBadge status={row.meetingStatus} registry={MEETING_STATUS_REGISTRY} size="sm" />
        </div>
        <div className="text-sm text-muted-foreground">
          {when(row.startedAt ?? row.startsAt)}
        </div>
        {row.exitReason && (
          <div className="text-sm">
            <ClampedText text={row.exitReason} lines={2} />
          </div>
        )}
        <div className="text-sm text-muted-foreground">{formatDuration(row.durationS)}</div>
      </div>
    );

    return {
      viewKey: 'meetings.bot-runs',
      cardRender,
      getRowId: (row) => row.id,
      rowHref: () => pathname, // no detail page — the reason IS the detail
      fetcher,
      exporter,
      searchPlaceholder: 'Search bot runs…',
      searchHints: ['Meeting', 'Exit reason'],
      defaultSort: { id: 'started', desc: true },
      exportFilename: 'meetings-bot-runs',
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'meeting', label: 'Meeting' },
        { id: 'started', label: 'Started' },
        { id: 'ended', label: 'Ended' },
        { id: 'reason', label: 'Exit reason' },
        { id: 'duration', label: 'Duration' },
      ],
      actions: [],
    };
  }, [items, pathname, timeZone]);
}
