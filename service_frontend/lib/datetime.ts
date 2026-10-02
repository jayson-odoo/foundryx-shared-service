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

type FormatStyle = 'date' | 'datetime' | 'time';

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
  return d ? getFormatter(style, options?.timeZone).format(d) : '-';
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
