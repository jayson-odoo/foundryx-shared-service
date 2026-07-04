/**
 * Shared datetime rendering (plan sprint-2/05, BL-012) — THE one formatter
 * family for backend timestamps.
 *
 * Contract: the DB stores UTC; the wire is ISO-8601. Until the backend
 * Z-suffixes everywhere, a tz-less string ("2026-01-01T10:00:00") is UTC BY
 * CONVENTION — `new Date()` would mis-parse it as local time, so `parseUtc`
 * pins naive strings to UTC explicitly. Rendering happens in the viewer's
 * timezone (`options.timeZone`, normally the session user's preference via
 * `useDatetime()`; omitted = browser tz).
 *
 * Null-safe: null/undefined/unparsable input renders '—'.
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
// hundreds — cache one formatter per (style, tz).
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
      // Invalid stored tz preference must never crash rendering — fall back
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
  return d ? getFormatter(style, options?.timeZone).format(d) : '—';
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
 * Calendar-day key ("2026-06-04") of the instant AS SEEN in the viewer's
 * timezone — for day grouping/separators (inbox threads). The same instant
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
