'use client';

/**
 * The Foundryx UIUX date range (playbook 0.71.0 "Date fields > Ranges"): one
 * field showing "1 Nov - 30 Nov 2026" that opens two months side by side (one
 * on phones), with quick picks down the left. The first click sets From, the
 * second sets To. `DateRangePicker` renders it while the switch is on, with
 * the same props.
 *
 * Quick picks and day totals count in the zone the report names (the
 * `timeZone` prop, the report's own zone), the same for every viewer.
 */
import { useRef, useState } from 'react';
import type { DateRange, Matcher } from 'react-day-picker';
import { CalendarIcon, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { dateKey } from '@/lib/datetime';
import { useMediaQuery } from '@/hooks/use-media-query';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  localDateKey,
  parseKey,
  resolvePresetRange,
  todayKeyInZone,
  type DateRangePickerProps,
  type DateRangePreset,
} from '@/components/platform/date-range-picker/date-range-picker';
import { FX_FIELD, FX_MENU } from './classes';
import { FxCalendar } from './fx-calendar';
import { DateRangeTypedInputs } from '@/components/platform/date-range-picker/date-range-typed-inputs';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** The quick picks, in the playbook's order, then the two SS already offered. */
export const FX_RANGE_PICKS: { label: string; value: DateRangePreset }[] = [
  { label: 'Today', value: 'today' },
  { label: 'This week', value: 'thisWeek' },
  { label: 'This month', value: 'thisMonth' },
  { label: 'Last month', value: 'lastMonth' },
  { label: 'This year', value: 'thisYear' },
  { label: 'Last 7 days', value: 'last7' },
  { label: 'Last 30 days', value: 'last30' },
];

function shift(key: string, days: number): string {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/**
 * A quick pick as concrete days in `tz`. Weeks start on Monday. The picks SS
 * already had resolve exactly as before (`resolvePresetRange`).
 */
export function resolveFxPresetRange(preset: DateRangePreset, tz: string, now: Date = new Date()): { from: string; to: string } {
  const today = dateKey(now, { timeZone: tz }) ?? now.toISOString().slice(0, 10);
  switch (preset) {
    case 'today':
      return { from: today, to: today };
    case 'thisWeek': {
      const [y, m, d] = today.split('-').map(Number);
      const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
      return { from: shift(today, -weekday), to: today };
    }
    case 'thisYear':
      return { from: `${today.slice(0, 4)}-01-01`, to: today };
    default:
      return resolvePresetRange(preset, tz);
  }
}

function part(key: string) {
  const [y, m, d] = key.split('-').map(Number);
  return { y, m, d };
}

/** "1 Nov - 30 Nov 2026"; "28 Dec 2025 - 3 Jan 2026"; "14 Nov 2026"; open ends read "From ..." / "Until ...". */
export function fxRangeLabel(from: string, to: string): string {
  const one = (k: string, year = true) => {
    const p = part(k);
    return `${p.d} ${MONTHS[p.m - 1]}${year ? ` ${p.y}` : ''}`;
  };
  if (from && !to) return `From ${one(from)}`;
  if (!from && to) return `Until ${one(to)}`;
  if (!from && !to) return '';
  if (from === to) return one(from);
  const sameYear = part(from).y === part(to).y;
  return `${one(from, !sameYear)} - ${one(to)}`;
}

export function FxDateRangePicker({ value, onChange, timeZone, className, minDate, maxDate }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<Date | null>(null);
  const [hovered, setHovered] = useState<Date | null>(null);
  // Controlled once a typed day jumps it; `undefined` = open on the value's month.
  const [month, setMonth] = useState<Date | undefined>(undefined);
  const wide = useMediaQuery('(min-width: 640px)');

  const pickPreset = (preset: DateRangePreset) => {
    const { from, to } = resolveFxPresetRange(preset, timeZone);
    onChange({ preset, from, to });
    anchorRef.current = null;
    setOpen(false);
  };

  // While picking the second day, the days between tint as you point.
  const anchor = anchorRef.current;
  const calendarValue: DateRange | undefined =
    anchor && hovered
      ? anchor <= hovered
        ? { from: anchor, to: hovered }
        : { from: hovered, to: anchor }
      : value.from || value.to
        ? { from: value.from ? parseKey(value.from) : undefined, to: value.to ? parseKey(value.to) : undefined }
        : undefined;

  const disabled: Matcher[] = [];
  if (minDate) disabled.push({ before: parseKey(minDate) });
  if (maxDate) disabled.push({ after: parseKey(maxDate) });

  const label = fxRangeLabel(value.from, value.to);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        anchorRef.current = null;
        setHovered(null);
        setMonth(undefined);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label ? `Date range: ${label}` : 'Date range'}
          data-fx-field=""
          className={cn(
            PRESSED_CLASS,
            FX_FIELD,
            'flex h-8.5 w-full items-center gap-2 px-3 text-start text-[0.8125rem] tabular-nums pointer-coarse:text-base sm:w-64',
            className,
          )}
        >
          <CalendarIcon className="size-4 shrink-0 text-(--fx-ink-3)" aria-hidden="true" />
          <span className="min-w-0 flex-1">{label}</span>
          <ChevronDown className="size-4 shrink-0 text-(--fx-ink-3)" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent className={cn(FX_MENU, 'w-auto max-w-[calc(100vw-1rem)] p-0')} align="start">
        <div className="flex flex-col sm:flex-row">
          <div
            role="group"
            aria-label="Quick picks"
            className="flex gap-1 overflow-x-auto border-b border-(--fx-line) p-2 sm:flex-col sm:overflow-visible sm:border-e sm:border-b-0"
          >
            {FX_RANGE_PICKS.map((pick) => (
              <button
                key={pick.value}
                type="button"
                aria-pressed={value.preset === pick.value}
                onClick={() => pickPreset(pick.value)}
                className={cn(
                  PRESSED_CLASS,
                  'shrink-0 whitespace-nowrap rounded-(--fx-r-s) px-2.5 py-1.5 text-start text-sm text-(--fx-ink-2) hover:bg-(--fx-surface-2) hover:text-(--fx-ink)',
                  'aria-pressed:bg-(--fx-link-bg) aria-pressed:font-semibold aria-pressed:text-(--fx-ink)',
                )}
              >
                {pick.label}
              </button>
            ))}
          </div>
          <div className="flex min-w-0 flex-col">
            <FxCalendar
              mode="range"
              numberOfMonths={wide ? 2 : 1}
              defaultMonth={value.from || value.to ? parseKey(value.from || value.to) : undefined}
              month={month}
              onMonthChange={setMonth}
              selected={calendarValue}
              disabled={disabled.length ? disabled : undefined}
              onDayMouseEnter={(day) => {
                if (anchorRef.current) setHovered(day);
              }}
              onSelect={(_range, day) => {
                if (!day) return;
                const first = anchorRef.current;
                if (!first) {
                  anchorRef.current = day;
                  setHovered(day);
                  const key = localDateKey(day);
                  onChange({ preset: 'custom', from: key, to: key });
                  return;
                }
                const [start, end] = first <= day ? [first, day] : [day, first];
                onChange({ preset: 'custom', from: localDateKey(start), to: localDateKey(end) });
                anchorRef.current = null;
                setHovered(null);
                setOpen(false);
              }}
            />
            <DateRangeTypedInputs
              className="border-(--fx-line)"
              from={value.from}
              to={value.to}
              minDate={minDate}
              maxDate={maxDate}
              today={todayKeyInZone(timeZone)}
              onChange={(from, to) => {
                anchorRef.current = null;
                setHovered(null);
                onChange({ preset: 'custom', from, to });
              }}
              onJump={(day) => setMonth(parseKey(day))}
            />
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
