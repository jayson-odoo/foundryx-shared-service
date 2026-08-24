'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import type { MeetingAttendee, MeetingsEvent, MeetingPlatform } from '@/types/meetings';
import { toCsv } from '@/lib/csv';
import { formatDateTime } from '@/lib/datetime';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const PLATFORM_LABELS: Record<MeetingPlatform, string> = {
  meet: 'Google Meet',
  zoom: 'Zoom',
  teams: 'Teams',
  other: 'Other',
};

function sortRows(rows: MeetingsEvent[], sort: ListQuery['sort']): MeetingsEvent[] {
  if (!sort) return rows;
  const val = (r: MeetingsEvent): string => {
    switch (sort.id) {
      case 'title':
        return r.title ?? '';
      case 'organiser':
        return r.organiserEmail ?? '';
      case 'platform':
        return PLATFORM_LABELS[r.platform];
      case 'endsAt':
        return r.endsAt ?? '';
      default:
        return r.startsAt;
    }
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

function attendeeLabel(a: MeetingAttendee): string {
  return a.displayName ?? a.email;
}

/**
 * Upcoming-events list config (S0 plan §4, AC-S0-7/8).
 *
 * The dataset is one user's next fortnight — small, already in memory from
 * `useMyMeetings` — so the fetcher pages over it client-side, the same
 * client-adapter pattern the quick-replies list uses. There is no detail page in
 * S0: the only per-row action is the capture switch, which is a control in the
 * row rather than an action-menu entry so the state is visible without opening
 * anything.
 *
 * The switch reads CAPTURE, not opt-out: it is ON by default and switching it
 * off is what sets `optedOut`. An opted-out row stays in the list, greyed.
 */
export function useUpcomingEventsListConfig(
  items: MeetingsEvent[],
  handlers: {
    timeZone: string | null;
    saving: boolean;
    onToggleCapture: (event: MeetingsEvent, capture: boolean) => void;
  },
): ResourceListConfig<MeetingsEvent> {
  const pathname = usePathname();
  const { timeZone, saving, onToggleCapture } = handlers;

  return useMemo<ResourceListConfig<MeetingsEvent>>(() => {
    const when = (iso: string | null): string => formatDateTime(iso, { timeZone });

    const columns: ColumnDef<MeetingsEvent>[] = [
      {
        id: 'title',
        accessorFn: (r) => r.title ?? '',
        meta: { headerTitle: 'Meeting' },
        header: ({ column }) => <DataGridColumnHeader title="Meeting" column={column} />,
        cell: ({ row }) => (
          <span className={row.original.optedOut ? 'text-muted-foreground' : undefined}>
            <ClampedText text={row.original.title ?? '—'} lines={2} />
          </span>
        ),
        size: 260,
        enableSorting: true,
      },
      {
        id: 'startsAt',
        accessorFn: (r) => r.startsAt,
        meta: { headerTitle: 'Starts' },
        header: ({ column }) => <DataGridColumnHeader title="Starts" column={column} />,
        cell: ({ row }) => (
          <span className={row.original.optedOut ? 'text-muted-foreground' : undefined}>
            {when(row.original.startsAt)}
          </span>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'endsAt',
        accessorFn: (r) => r.endsAt ?? '',
        meta: { headerTitle: 'Ends' },
        header: ({ column }) => <DataGridColumnHeader title="Ends" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{when(row.original.endsAt)}</span>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'organiser',
        accessorFn: (r) => r.organiserEmail ?? '',
        meta: { headerTitle: 'Organiser' },
        header: ({ column }) => <DataGridColumnHeader title="Organiser" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={row.original.organiserEmail ?? '—'} lines={1} />
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'attendees',
        accessorFn: (r) => r.attendeeCount,
        meta: { headerTitle: 'Attendees' },
        header: ({ column }) => <DataGridColumnHeader title="Attendees" column={column} />,
        cell: ({ row }) => (
          <OverflowPills
            items={row.original.attendees}
            keyFor={(a) => a.email}
            renderPill={(a) => (
              <Badge variant="secondary" appearance="light" size="sm">
                {attendeeLabel(a)}
              </Badge>
            )}
          />
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'platform',
        accessorFn: (r) => PLATFORM_LABELS[r.platform],
        meta: { headerTitle: 'Platform' },
        header: ({ column }) => <DataGridColumnHeader title="Platform" column={column} />,
        cell: ({ row }) => (
          <Badge variant="outline" size="sm">
            {PLATFORM_LABELS[row.original.platform]}
          </Badge>
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'capture',
        meta: { headerTitle: 'Capture', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Capture" column={column} />,
        cell: ({ row }) => (
          <div onClick={stop} className="flex justify-end">
            <Switch
              aria-label={`Capture ${row.original.title ?? 'this meeting'}`}
              checked={!row.original.optedOut}
              disabled={saving}
              onCheckedChange={(checked) => onToggleCapture(row.original, checked)}
            />
          </div>
        ),
        size: 110,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<MeetingsEvent>> => {
      let rows = items;
      if (query.search) {
        const s = query.search.toLowerCase();
        rows = rows.filter(
          (r) =>
            (r.title ?? '').toLowerCase().includes(s) ||
            (r.organiserEmail ?? '').toLowerCase().includes(s) ||
            r.attendees.some((a) => attendeeLabel(a).toLowerCase().includes(s)),
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
        ['Meeting', 'Starts', 'Ends', 'Organiser', 'Attendees', 'Platform', 'Capture'],
        data.map((r) => [
          r.title ?? '',
          when(r.startsAt),
          when(r.endsAt),
          r.organiserEmail ?? '',
          r.attendeeCount,
          PLATFORM_LABELS[r.platform],
          r.optedOut ? 'No' : 'Yes',
        ]),
      );
    };

    return {
      viewKey: 'meetings.upcoming-events',
      getRowId: (row) => row.id,
      rowHref: () => pathname, // no detail page in S0 — the row IS the control
      fetcher,
      exporter,
      searchPlaceholder: 'Search meetings…',
      searchHints: ['Meeting', 'Organiser', 'Attendee'],
      defaultSort: { id: 'startsAt', desc: false },
      exportFilename: 'upcoming-meetings',
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'title', label: 'Meeting' },
        { id: 'startsAt', label: 'Starts' },
        { id: 'endsAt', label: 'Ends' },
        { id: 'organiser', label: 'Organiser' },
        { id: 'attendees', label: 'Attendees' },
        { id: 'platform', label: 'Platform' },
        { id: 'capture', label: 'Capture' },
      ],
      actions: [],
    };
  }, [items, pathname, saving, timeZone, onToggleCapture]);
}
