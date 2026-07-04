import { describe, expect, it } from 'vitest';
import {
  dateKey,
  formatDate,
  formatDateTime,
  formatTime,
  parseUtc,
} from './datetime';

describe('parseUtc', () => {
  it('pins a naive (tz-less) backend string to UTC', () => {
    const d = parseUtc('2026-01-01T10:00:00');
    expect(d?.toISOString()).toBe('2026-01-01T10:00:00.000Z');
  });

  it('handles fractional seconds without a designator', () => {
    const d = parseUtc('2026-01-01T10:00:00.123456');
    expect(d?.toISOString()).toBe('2026-01-01T10:00:00.123Z');
  });

  it('passes Z-suffixed and offset strings through unchanged', () => {
    expect(parseUtc('2026-01-01T10:00:00Z')?.toISOString()).toBe(
      '2026-01-01T10:00:00.000Z',
    );
    expect(parseUtc('2026-01-01T10:00:00+02:00')?.toISOString()).toBe(
      '2026-01-01T08:00:00.000Z',
    );
  });

  it('returns null for null/empty/garbage', () => {
    expect(parseUtc(null)).toBeNull();
    expect(parseUtc(undefined)).toBeNull();
    expect(parseUtc('')).toBeNull();
    expect(parseUtc('not-a-date')).toBeNull();
  });
});

describe('formatters render in the requested timezone', () => {
  const iso = '2026-01-01T10:00:00'; // naive UTC by convention

  it('formatDateTime shifts into the viewer tz', () => {
    expect(formatDateTime(iso, { timeZone: 'UTC' })).toBe('01 Jan 2026, 10:00');
    // UTC+8 — same instant, evening local time
    expect(formatDateTime(iso, { timeZone: 'Asia/Singapore' })).toBe(
      '01 Jan 2026, 18:00',
    );
  });

  it('formatDate can land on a DIFFERENT calendar day in the viewer tz', () => {
    const lateUtc = '2026-01-01T23:30:00';
    expect(formatDate(lateUtc, { timeZone: 'UTC' })).toBe('01 Jan 2026');
    expect(formatDate(lateUtc, { timeZone: 'Asia/Tokyo' })).toBe('02 Jan 2026');
  });

  it('formatTime renders HH:mm in the viewer tz', () => {
    expect(formatTime(iso, { timeZone: 'UTC' })).toBe('10:00');
    expect(formatTime(iso, { timeZone: 'America/New_York' })).toBe('05:00');
  });

  it('renders the em dash for null/invalid input', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatTime('garbage')).toBe('—');
  });

  it('falls back to the browser tz on an invalid stored preference', () => {
    // must not throw — bad pref must never crash a list render
    expect(() => formatDateTime(iso, { timeZone: 'Not/AZone' })).not.toThrow();
    expect(formatDateTime(iso, { timeZone: 'Not/AZone' })).toMatch(/Jan 2026/);
  });
});

describe('dateKey', () => {
  it('keys by the calendar day in the viewer tz, not UTC', () => {
    const lateUtc = '2026-01-01T23:30:00';
    expect(dateKey(lateUtc, { timeZone: 'UTC' })).toBe('2026-01-01');
    expect(dateKey(lateUtc, { timeZone: 'Asia/Tokyo' })).toBe('2026-01-02');
    expect(dateKey(lateUtc, { timeZone: 'America/New_York' })).toBe(
      '2026-01-01',
    );
  });

  it('accepts Date objects and returns null on invalid input', () => {
    expect(dateKey(new Date('2026-01-01T12:00:00Z'), { timeZone: 'UTC' })).toBe(
      '2026-01-01',
    );
    expect(dateKey(null)).toBeNull();
    expect(dateKey('garbage')).toBeNull();
  });
});
