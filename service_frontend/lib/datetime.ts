/**
 * Shared datetime rendering (plan sprint-2/05, BL-012) - THE one formatter
 * family for backend timestamps.
 *
 * Contract: the DB stores UTC; the wire is ISO-8601. Until the backend
 * Z-suffixes everywhere, a tz-less string ("2026-01-01T10:00:00") is UTC BY
 * CONVENTION - `new Date()` would mis-parse it as local time, so `parseUtc`
 * pins naive strings to UTC explicitly. Rendering happens in the viewer's
 * timezone (`options.timeZone`, normally the session user's preference via
 * `useDatetime()`; omitted = browser tz).
 *
 * Null-safe: null/undefined/unparsable input renders '-'.
 */

export interface DatetimeFormatOptions {
  /** IANA timezone name; omitted/invalid = browser timezone. */
  timeZone?: string | null;
}

/** Datetime string with no timezone designator (no Z, no ±hh:mm). */
const NAIVE_DATETIME =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(NAIVE_DATETIME.test(iso) ? `${iso}Z` : iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

type FormatStyle = 'date' | 'datetime' | 'time' | 'dmy';

const STYLE_OPTIONS: Record<FormatStyle, Intl.DateTimeFormatOptions> = {
  // en-GB keeps the established display shape: 02 Jan 2024 13:45
  date: { day: '2-digit', month: 'short', year: 'numeric' },
  datetime: {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  },
  time: { hour: '2-digit', minute: '2-digit' },
  // 05/11/2026, 3:04 pm - the 12-hour value is built in formatDmy, never left to the ICU hour cycle
  dmy: {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  },
};

// Intl.DateTimeFormat construction is expensive and list cells render in the
// hundreds - cache one formatter per (style, tz).
const formatterCache = new Map<string, Intl.DateTimeFormat>();

function getFormatter(style: FormatStyle, timeZone?: string | null): Intl.DateTimeFormat {
  const tz = timeZone ?? '';
  const key = `${style}|${tz}`;
  let formatter = formatterCache.get(key);
  if (!formatter) {
    try {
      formatter = new Intl.DateTimeFormat('en-GB', {
        ...STYLE_OPTIONS[style],
        timeZone: timeZone ?? undefined,
      });
    } catch {
      // Invalid stored tz preference must never crash rendering - fall back
      // to the browser timezone.
      formatter = new Intl.DateTimeFormat('en-GB', STYLE_OPTIONS[style]);
    }
    formatterCache.set(key, formatter);
  }
  return formatter;
}

function format(
  style: FormatStyle,
  iso: string | null | undefined,
  options?: DatetimeFormatOptions,
): string {
  const d = parseUtc(iso);
  if (!d) return '-';
  const formatter = getFormatter(style, options?.timeZone);
  return style === 'dmy' ? formatDmy(formatter, d) : formatter.format(d);
}

/** "05/11/2026, 3:04 pm" from 24-hour parts (0 -> 12 am, 12 -> 12 pm), whatever the locale data says. */
function formatDmy(formatter: Intl.DateTimeFormat, d: Date): string {
  const part = (type: string) => formatter.formatToParts(d).find((p) => p.type === type)?.value ?? '';
  const hour24 = Number(part('hour')) % 24;
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${part('day')}/${part('month')}/${part('year')}, ${hour12}:${part('minute')} ${hour24 < 12 ? 'am' : 'pm'}`;
}

/** "02 Jan 2024" in the viewer's timezone. */
export function formatDate(
  iso: string | null | undefined,
  options?: DatetimeFormatOptions,
): string {
  return format('date', iso, options);
}

/** "02 Jan 2024, 13:45" in the viewer's timezone. */
export function formatDateTime(
  iso: string | null | undefined,
  options?: DatetimeFormatOptions,
): string {
  return format('datetime', iso, options);
}

/** "05/11/2026, 3:04 pm" (dd/mm/yyyy, h:mm am/pm) in the viewer's timezone. */
export function formatDmyDateTime(
  iso: string | null | undefined,
  options?: DatetimeFormatOptions,
): string {
  return format('dmy', iso, options);
}

/** "13:45" in the viewer's timezone. */
export function formatTime(
  iso: string | null | undefined,
  options?: DatetimeFormatOptions,
): string {
  return format('time', iso, options);
}

/**
 * Reverse direction (plan 29, AC-BRD-08): a `<input type="datetime-local">`
 * carries a bare wall-clock string with NO timezone - `zonedTimeToUtc` treats
 * it as a wall-clock reading IN the given IANA zone and returns the matching
 * UTC instant (guess-then-correct via `Intl.DateTimeFormat`, no date library).
 * `utcToZonedInputValue` is the inverse, for prefilling the same input from a
 * stored UTC instant. Both accept a `null` zone (browser tz) like every other
 * helper in this file. A single-pass correction is exact except exactly at a
 * DST transition edge - the same accepted simplification the workflow
 * scheduler already carries (see CLAUDE.md "Workflow Engine" notes).
 */
export function zonedTimeToUtc(wallClockLocal: string, timeZone?: string | null): Date | null {
  const m = wallClockLocal.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!m) return null;
  const [, y, mo, d, h, mi, s] = m;
  const guessUtcMs = Date.UTC(+y, +mo - 1, +d, +h, +mi, s ? +s : 0);
  const tz = timeZone ?? browserTimeZone();
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return new Date(guessUtcMs);
  }
  const parts = formatter.formatToParts(new Date(guessUtcMs));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '0';
  // Intl's 24h "00" for midnight sometimes renders "24" - normalize.
  const hour = get('hour') === '24' ? 0 : Number(get('hour'));
  const asIfLocalMs = Date.UTC(
    Number(get('year')),
    Number(get('month')) - 1,
    Number(get('day')),
    hour,
    Number(get('minute')),
    Number(get('second')),
  );
  const offsetMs = guessUtcMs - asIfLocalMs;
  return new Date(guessUtcMs + offsetMs);
}

/** ISO UTC instant -> the wall-clock string a `datetime-local` input expects,
 *  AS SEEN in the given (or browser) timezone. */
export function utcToZonedInputValue(iso: string | null | undefined, timeZone?: string | null): string {
  const d = parseUtc(iso);
  if (!d) return '';
  const tz = timeZone ?? browserTimeZone();
  try {
    const formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
    const parts = formatter.formatToParts(d);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';
    const hour = get('hour') === '24' ? '00' : get('hour');
    return `${get('year')}-${get('month')}-${get('day')}T${hour}:${get('minute')}`;
  } catch {
    return '';
  }
}

/**
 * Calendar-day key ("2026-06-04") of the instant AS SEEN in the viewer's
 * timezone - for day grouping/separators (inbox threads). The same instant
 * lands on different days in different timezones; never key off getUTCDate.
 */
export function dateKey(
  date: Date | string | null | undefined,
  options?: DatetimeFormatOptions,
): string | null {
  const d = typeof date === 'string' ? parseUtc(date) : (date ?? null);
  if (!d || Number.isNaN(d.getTime())) return null;
  const tz = options?.timeZone ?? undefined;
  try {
    // en-CA formats as YYYY-MM-DD.
    return new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(d);
  } catch {
    return new Intl.DateTimeFormat('en-CA').format(d);
  }
}

/** "05/11/2026" from a calendar-day key ("2026-11-05"); a pure string rewrite, so no timezone can shift the day. */
export function formatDmyDate(dayKey: string | null | undefined): string {
  const m = (dayKey ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : '-';
}

/* ───────────── Foundryx UIUX switch: moments (playbook-uiux.md) ─────────────
 * New functions only; everything above is untouched, so with the switch off
 * no string changes. `useDatetime()` swaps to these while the switch is on.
 * Playbook 0.71.0 "Date fields" plus the gap audit's "Times and time zones":
 * dates read "14 Nov 2026", moments "14 Nov 2026, 2:14 pm" on a 12-hour
 * clock, recent ones in lists read relative, long feeds get day lines.
 */

const FX_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface FxParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: string;
}

const fxPartsCache = new Map<string, Intl.DateTimeFormat>();

/** The instant's wall-clock parts in `timeZone` (null/invalid = browser zone). */
function fxParts(d: Date, timeZone?: string | null): FxParts {
  const key = timeZone ?? '';
  let formatter = fxPartsCache.get(key);
  if (!formatter) {
    const opts: Intl.DateTimeFormatOptions = {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    };
    try {
      formatter = new Intl.DateTimeFormat('en-GB', { ...opts, timeZone: timeZone ?? undefined });
    } catch {
      formatter = new Intl.DateTimeFormat('en-GB', opts);
    }
    fxPartsCache.set(key, formatter);
  }
  const parts = formatter.formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '0';
  return {
    year: Number(get('year')),
    month: Number(get('month')),
    day: Number(get('day')),
    hour: Number(get('hour')) % 24,
    minute: get('minute').padStart(2, '0'),
  };
}

function fxDayText(p: Pick<FxParts, 'year' | 'month' | 'day'>, withYear = true): string {
  const base = `${p.day} ${FX_MONTHS[p.month - 1]}`;
  return withYear ? `${base} ${p.year}` : base;
}

function fxClock(p: FxParts): string {
  const hour12 = p.hour % 12 === 0 ? 12 : p.hour % 12;
  return `${hour12}:${p.minute} ${p.hour < 12 ? 'am' : 'pm'}`;
}

/** Whole days from calendar day `a` to `b` (both y/m/d), ignoring zones. */
function fxDayDiff(a: Pick<FxParts, 'year' | 'month' | 'day'>, b: Pick<FxParts, 'year' | 'month' | 'day'>): number {
  return Math.round((Date.UTC(b.year, b.month - 1, b.day) - Date.UTC(a.year, a.month - 1, a.day)) / 86_400_000);
}

export interface FxMomentOptions extends DatetimeFormatOptions {
  /** The clock to compare against (tests pin it); default now. */
  now?: Date;
}

/** "14 Nov 2026" from a calendar-day key ("2026-11-14"); a pure string rewrite. */
export function formatFxDayKey(dayKey: string | null | undefined): string {
  const m = (dayKey ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return '-';
  const month = Number(m[2]);
  if (month < 1 || month > 12) return '-';
  return fxDayText({ year: Number(m[1]), month, day: Number(m[3]) });
}

/** "14 Nov 2026" in the viewer's zone. */
export function formatFxDate(iso: string | null | undefined, options?: DatetimeFormatOptions): string {
  const d = parseUtc(iso);
  return d ? fxDayText(fxParts(d, options?.timeZone)) : '-';
}

/** "2:14 pm" in the viewer's zone (12-hour clock). */
export function formatFxTime(iso: string | null | undefined, options?: DatetimeFormatOptions): string {
  const d = parseUtc(iso);
  return d ? fxClock(fxParts(d, options?.timeZone)) : '-';
}

/** "14 Nov 2026, 2:14 pm" in the viewer's zone. */
export function formatFxDateTime(iso: string | null | undefined, options?: DatetimeFormatOptions): string {
  const d = parseUtc(iso);
  if (!d) return '-';
  const p = fxParts(d, options?.timeZone);
  return `${fxDayText(p)}, ${fxClock(p)}`;
}

/**
 * A recent moment in a list or feed: "now" (under a minute), "5 min", "3 h"
 * (under a day), "Yesterday" (older, on the calendar day before today), then "14 Nov"
 * ("14 Nov 2025" in another year). A future moment reads in full. Show the
 * full form (`formatFxDateTime`) as its tooltip.
 */
export function formatFxRelative(iso: string | null | undefined, options?: FxMomentOptions): string {
  const d = parseUtc(iso);
  if (!d) return '-';
  const now = options?.now ?? new Date();
  const seconds = (now.getTime() - d.getTime()) / 1000;
  if (seconds < -60) return formatFxDateTime(iso, options);
  if (seconds < 60) return 'now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h`;
  const p = fxParts(d, options?.timeZone);
  const today = fxParts(now, options?.timeZone);
  if (fxDayDiff(p, today) === 1) return 'Yesterday';
  return fxDayText(p, p.year !== today.year);
}

/** The line between days in a long feed: "Today", "Yesterday", "14 Nov 2026". */
export function formatFxDayLine(iso: string | null | undefined, options?: FxMomentOptions): string {
  const d = parseUtc(iso);
  if (!d) return '-';
  const p = fxParts(d, options?.timeZone);
  const diff = fxDayDiff(p, fxParts(options?.now ?? new Date(), options?.timeZone));
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return fxDayText(p);
}

/**
 * The zone line under a time picker: "Kuala Lumpur time (GMT+8)". The place is
 * the zone's own city; the offset is the one in force at `at` (default now).
 */
export function formatFxZoneLine(timeZone?: string | null, at: Date = new Date()): string {
  const tz = timeZone || browserTimeZone();
  let offset = 'GMT';
  try {
    const part = new Intl.DateTimeFormat('en-GB', { timeZone: tz, timeZoneName: 'shortOffset' })
      .formatToParts(at)
      .find((p) => p.type === 'timeZoneName')?.value;
    if (part) offset = part.replace(/^UTC/, 'GMT').replace(/^GMT[+-]0$/, 'GMT');
  } catch {
    return `${tz} time`;
  }
  const city = tz === 'UTC' || tz === 'Etc/UTC' ? 'UTC' : (tz.split('/').pop() ?? tz).replace(/_/g, ' ');
  return `${city} time (${offset})`;
}
