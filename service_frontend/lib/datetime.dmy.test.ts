/**
 * Plan 63 (AC-63-35, RED): `formatDmyDateTime` - "05/11/2026, 3:04 pm" in the viewer's timezone,
 * sibling of `formatDateTime` (same null-safety, same `{ timeZone }` option).
 */
import { describe, expect, it } from 'vitest';
import * as datetime from './datetime';

const MYT = { timeZone: 'Asia/Kuala_Lumpur' };

function dmy(iso: string | null | undefined, options?: { timeZone?: string | null }): string {
  const fn = (datetime as Record<string, unknown>).formatDmyDateTime as
    | ((v: string | null | undefined, o?: { timeZone?: string | null }) => string)
    | undefined;
  if (typeof fn !== 'function') throw new Error('lib/datetime.ts does not export formatDmyDateTime');
  return fn(iso, options);
}

describe('formatDmyDateTime (AC-63-35)', () => {
  it('renders dd/mm/yyyy, h:mm am/pm in the given timezone (MYT = UTC+8)', () => {
    expect(dmy('2026-11-05T07:04:00Z', MYT)).toBe('05/11/2026, 3:04 pm');
  });

  it('pads day and month, never the hour', () => {
    expect(dmy('2026-01-02T01:05:00Z', MYT)).toBe('02/01/2026, 9:05 am');
  });

  it('uses 12 am / 12 pm at the boundaries, lower-case', () => {
    expect(dmy('2026-11-05T16:30:00Z', MYT)).toBe('06/11/2026, 12:30 am');
    expect(dmy('2026-11-05T04:30:00Z', MYT)).toBe('05/11/2026, 12:30 pm');
  });

  it('crosses the date line with the timezone (UTC evening is the next MYT day)', () => {
    expect(dmy('2026-12-31T20:00:00Z', MYT)).toBe('01/01/2027, 4:00 am');
    expect(dmy('2026-12-31T20:00:00Z', { timeZone: 'UTC' })).toBe('31/12/2026, 8:00 pm');
  });

  it('pins a tz-less backend string to UTC like every sibling formatter', () => {
    expect(dmy('2026-11-05T07:04:00', MYT)).toBe('05/11/2026, 3:04 pm');
  });

  it('is null-safe: null, undefined, empty and garbage render "-"', () => {
    for (const bad of [null, undefined, '', 'not a date']) expect(dmy(bad, MYT)).toBe('-');
  });

  it('falls back to the browser timezone for an invalid zone instead of throwing', () => {
    expect(dmy('2026-11-05T07:04:00Z', { timeZone: 'Not/AZone' })).toMatch(/^\d{2}\/\d{2}\/\d{4}, \d{1,2}:\d{2} (am|pm)$/);
  });
});

describe('formatDmyDate', () => {
  it('rewrites a day key to dd/mm/yyyy and is null-safe', () => {
    expect((datetime as Record<string, unknown>).formatDmyDate).toBeTypeOf('function');
    const fn = (datetime as unknown as { formatDmyDate: (v: string | null | undefined) => string }).formatDmyDate;
    expect(fn('2026-11-05')).toBe('05/11/2026');
    expect(fn('')).toBe('-');
    expect(fn(null)).toBe('-');
  });
});
