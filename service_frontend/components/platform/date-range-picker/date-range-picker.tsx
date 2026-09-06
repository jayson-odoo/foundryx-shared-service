'use client';

/**
 * Shared date-range control (plan 30, D-A9-15 flagged item 4) - assembled
 * from the EXISTING `Popover` + `Calendar` (already `react-day-picker`, so
 * `mode="range"` is free) + a preset `SearchSelect`. No new dependency.
 * Lives in `components/platform/` because A4 broadcasts wants the same
 * control (plan 30 §2.2).
 *
 * Foolproof-UI: the preset `SearchSelect` offers ONLY the five valid presets
 * (no free-text). Picking a preset resolves `from`/`to` immediately from the
 * REPORT timezone's "today" (never the browser's) so the dashboard/report
 * query lines up with what the user sees. "Custom" opens the calendar
 * popover; picking two days there sets `preset: 'custom'` and the exact
 * range - the trigger button always shows the CURRENT effective range,
 * whichever control set it.
 */
import { useRef, useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { CalendarIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { SearchSelect } from '@/components/platform/search-select';
import { dateKey } from '@/lib/datetime';
import { cn } from '@/lib/utils';

export type DateRangePreset = 'last7' | 'last30' | 'thisMonth' | 'lastMonth' | 'custom';

export interface DateRangeValue {
  preset: DateRangePreset;
  /** YYYY-MM-DD, inclusive, LOCAL to `timeZone`. */
  from: string;
  /** YYYY-MM-DD, inclusive, LOCAL to `timeZone`. */
  to: string;
}

export interface DateRangePickerProps {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  /** IANA zone the presets resolve "today" against - always the report
   *  timezone (`useDatetime().timeZone`), never the browser's. */
  timeZone: string;
  className?: string;
}

const PRESET_OPTIONS: { label: string; value: DateRangePreset }[] = [
  { label: 'Last 7 days', value: 'last7' },
  { label: 'Last 30 days', value: 'last30' },
  { label: 'This month', value: 'thisMonth' },
  { label: 'Last month', value: 'lastMonth' },
  { label: 'Custom', value: 'custom' },
];

/** "Today" as {y,m,d} in `tz`, via the existing `dateKey` helper (never a
 *  bespoke tz-math routine). */
function todayInZone(tz: string): { y: number; m: number; d: number } {
  const key = dateKey(new Date(), { timeZone: tz }) ?? new Date().toISOString().slice(0, 10);
  const [y, m, d] = key.split('-').map(Number);
  return { y, m, d };
}

function toKey(y: number, m: number, d: number): string {
  return new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
}

/** Resolves a preset to a concrete `{from, to}` (both inclusive, local
 *  calendar dates) - exported for the vitest suite + `use-report-filters`. */
export function resolvePresetRange(preset: DateRangePreset, tz: string): { from: string; to: string } {
  const { y, m, d } = todayInZone(tz);
  const todayKey = toKey(y, m, d);

  switch (preset) {
    case 'last7': {
      const from = new Date(Date.UTC(y, m - 1, d));
      from.setUTCDate(from.getUTCDate() - 6);
      return { from: from.toISOString().slice(0, 10), to: todayKey };
    }
    case 'last30': {
      const from = new Date(Date.UTC(y, m - 1, d));
      from.setUTCDate(from.getUTCDate() - 29);
      return { from: from.toISOString().slice(0, 10), to: todayKey };
    }
    case 'thisMonth':
      return { from: toKey(y, m, 1), to: todayKey };
    case 'lastMonth': {
      const prevMonth = m === 1 ? 12 : m - 1;
      const prevYear = m === 1 ? y - 1 : y;
      const lastDay = new Date(Date.UTC(prevYear, prevMonth, 0)).getUTCDate();
      return { from: toKey(prevYear, prevMonth, 1), to: toKey(prevYear, prevMonth, lastDay) };
    }
    case 'custom':
    default:
      return { from: todayKey, to: todayKey };
  }
}

/**
 * A `YYYY-MM-DD` key back into a calendar Date - built from LOCAL components
 * (S-6, review round 1). It used to build `Date.UTC(...)`, i.e. UTC midnight,
 * while `react-day-picker` matches `selected`/`defaultMonth` against Dates at
 * LOCAL midnight and hands back local-midnight Dates on click. West of UTC,
 * UTC midnight is the PREVIOUS local day - so `2026-03-01` highlighted Feb 28
 * and the popover opened on the wrong month, even though the value written
 * back (via `localDateKey`) was correct. The two halves must agree:
 * `localDateKey(parseKey(k)) === k` in every timezone.
 */
export function parseKey(key: string): Date {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/**
 * `react-day-picker` hands back a Date at LOCAL midnight for the clicked
 * day - `toISOString()` would convert THROUGH UTC and shift the calendar
 * date by a day in any timezone ahead of UTC. Read the local
 * year/month/date components instead (matches how the picker built it).
 */
export function localDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function displayLabel(from: string, to: string): string {
  // No `timeZone` override - `parseKey` now returns LOCAL midnight, so
  // formatting it in UTC would shift the label a day west of UTC.
  const fmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });
  const fromLabel = fmt.format(parseKey(from));
  const toLabel = fmt.format(parseKey(to));
  return from === to ? fromLabel : `${fromLabel} - ${toLabel}`;
}

export function DateRangePicker({ value, onChange, timeZone, className }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  // Our own two-click anchor, rather than trusting react-day-picker's
  // built-in range-merge heuristic (which can hand back a COMPLETE-looking
  // range - `to` still the PREVIOUS selection's end - on the very FIRST
  // click of a fresh pick, closing the popover before the user chose an end
  // date at all). Reset whenever the popover (re)opens.
  const anchorRef = useRef<Date | null>(null);

  const onPresetChange = (preset: string) => {
    const next = preset as DateRangePreset;
    if (next === 'custom') {
      // Foolproof-UI: don't silently collapse the range to "today" - open the
      // calendar so the user picks the actual custom range next.
      onChange({ ...value, preset: 'custom' });
      setOpen(true);
      return;
    }
    const { from, to } = resolvePresetRange(next, timeZone);
    onChange({ preset: next, from, to });
  };

  const calendarValue: DateRange | undefined = value.from
    ? { from: parseKey(value.from), to: value.to ? parseKey(value.to) : undefined }
    : undefined;

  return (
    <div className={cn('flex flex-col gap-2 sm:flex-row sm:items-center', className)}>
      <SearchSelect
        ariaLabel="Date range preset"
        className="w-full sm:w-44"
        value={value.preset}
        onChange={onPresetChange}
        options={PRESET_OPTIONS}
      />
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          anchorRef.current = null;
        }}
      >
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="w-full justify-start gap-2 font-normal sm:w-56"
          >
            <CalendarIcon className="size-4 text-muted-foreground" />
            <span>{displayLabel(value.from, value.to)}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="range"
            numberOfMonths={1}
            // Open showing the CURRENT value's month, not always "today" -
            // react-day-picker defaults to today's month otherwise, which
            // would force a user editing a March range to page forward/back
            // several months just to see it (Popover content unmounts on
            // close, so this recomputes fresh on every open).
            defaultMonth={value.from ? parseKey(value.from) : undefined}
            selected={calendarValue}
            onSelect={(_range, selectedDay) => {
              if (!selectedDay) return;
              const anchor = anchorRef.current;
              if (!anchor) {
                anchorRef.current = selectedDay;
                const key = localDateKey(selectedDay);
                onChange({ preset: 'custom', from: key, to: key });
                return;
              }
              const [start, end] = anchor <= selectedDay ? [anchor, selectedDay] : [selectedDay, anchor];
              onChange({ preset: 'custom', from: localDateKey(start), to: localDateKey(end) });
              anchorRef.current = null;
              setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
