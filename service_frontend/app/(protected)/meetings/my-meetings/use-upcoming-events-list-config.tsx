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
import { formatDateTime, formatTime } from '@/lib/datetime';

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
    const whenRange = (row: MeetingsEvent): string => {
      const start = when(row.startsAt);
      // An all-day or open-ended event has no end to append.
      if (!row.endsAt) return start;
      return `${start}-${formatTime(row.endsAt, { timeZone })}`;
    };

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
        size: 175,
        enableSorting: true,
      },
      {
        // Start AND end in ONE column: seven separate columns do not fit beside
        // the sidebar at 1280px, and "02:57-03:57" is how a person reads a
        // meeting time anyway. Both ends of the AC are still on screen.
        id: 'when',
        accessorFn: (r) => r.startsAt,
        meta: { headerTitle: 'When' },
        header: ({ column }) => <DataGridColumnHeader title="When" column={column} />,
        cell: ({ row }) => (
          <span className={row.original.optedOut ? 'text-muted-foreground' : undefined}>
            {whenRange(row.original)}
          </span>
        ),
        size: 215,
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
        size: 165,
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
        size: 145,
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
        size: 90,
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

    // Card view (the shared list's own prop, not a parallel component): at 375px
    // the grid has to scroll sideways to reach the capture switch, and that
    // switch is the entire point of the page.
    const cardRender = (row: MeetingsEvent) => (
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <span
            className={`text-sm font-medium ${row.optedOut ? 'text-muted-foreground' : ''}`}
          >
            <ClampedText text={row.title ?? '—'} lines={2} />
          </span>
          <div onClick={stop}>
            <Switch
              aria-label={`Capture ${row.title ?? 'this meeting'}`}
              checked={!row.optedOut}
              disabled={saving}
              onCheckedChange={(checked) => onToggleCapture(row, checked)}
            />
          </div>
        </div>
        <div className="text-sm text-muted-foreground">{whenRange(row)}</div>
        <div className="text-sm">
          <ClampedText text={row.organiserEmail ?? '—'} lines={1} />
        </div>
        <OverflowPills
          items={row.attendees}
          keyFor={(a) => a.email}
          renderPill={(a) => (
            <Badge variant="secondary" appearance="light" size="sm">
              {attendeeLabel(a)}
            </Badge>
          )}
        />
        <div>
          <Badge variant="outline" size="sm">
            {PLATFORM_LABELS[row.platform]}
          </Badge>
        </div>
      </div>
    );

    return {
      viewKey: 'meetings.upcoming-events',
      cardRender,
      getRowId: (row) => row.id,
      rowHref: () => pathname, // no detail page in S0 — the row IS the control
      fetcher,
      exporter,
      searchPlaceholder: 'Search meetings…',
      searchHints: ['Meeting', 'Organiser', 'Attendee'],
      defaultSort: { id: 'when', desc: false },
      exportFilename: 'upcoming-meetings',
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'title', label: 'Meeting' },
        { id: 'when', label: 'When' },
        { id: 'organiser', label: 'Organiser' },
        { id: 'attendees', label: 'Attendees' },
        { id: 'platform', label: 'Platform' },
        { id: 'capture', label: 'Capture' },
      ],
      actions: [],
    };
  }, [items, pathname, saving, timeZone, onToggleCapture]);
}
