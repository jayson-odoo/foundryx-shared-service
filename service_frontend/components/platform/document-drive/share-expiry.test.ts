import { describe, expect, it } from 'vitest';
import { shareExpiryDay, shareExpiryInstant, shareExpiryMinDay, shareLastMoment } from './share-expiry';

const KL = 'Asia/Kuala_Lumpur';
const LA = 'America/Los_Angeles';
const SYD = 'Australia/Sydney';

describe('share expiry as a day in the zone', () => {
  it('a day ends at the first moment of the next day in the zone', () => {
    expect(shareExpiryInstant('2026-12-31', KL)).toBe('2026-12-31T16:00:00.000Z');
    expect(shareExpiryInstant('2026-12-31', LA)).toBe('2027-01-01T08:00:00.000Z');
    expect(shareExpiryInstant('2026-12-31', 'UTC')).toBe('2027-01-01T00:00:00.000Z');
  });

  it('uses the offset in force on that night where the clocks change', () => {
    // Los Angeles: clocks go forward at 02:00 on 14 Mar 2027.
    expect(shareExpiryInstant('2027-03-13', LA)).toBe('2027-03-14T08:00:00.000Z');
    expect(shareExpiryInstant('2027-03-14', LA)).toBe('2027-03-15T07:00:00.000Z');
    // and back at 02:00 on 7 Nov 2027.
    expect(shareExpiryInstant('2027-11-06', LA)).toBe('2027-11-07T07:00:00.000Z');
    expect(shareExpiryInstant('2027-11-07', LA)).toBe('2027-11-08T08:00:00.000Z');
    // Sydney: clocks go forward at 02:00 on 4 Oct 2026, back at 03:00 on 4 Apr 2027.
    expect(shareExpiryInstant('2026-10-03', SYD)).toBe('2026-10-03T14:00:00.000Z');
    expect(shareExpiryInstant('2026-10-04', SYD)).toBe('2026-10-04T13:00:00.000Z');
    expect(shareExpiryInstant('2027-04-03', SYD)).toBe('2027-04-03T13:00:00.000Z');
    expect(shareExpiryInstant('2027-04-04', SYD)).toBe('2027-04-04T14:00:00.000Z');
  });

  it('a stored expiry reads back as the same day in the same zone', () => {
    for (const zone of [KL, LA, SYD, 'UTC', 'Europe/London']) {
      for (const day of ['2026-12-31', '2027-03-13', '2027-03-14', '2026-10-03', '2026-10-04', '2027-04-04']) {
        expect(shareExpiryDay(shareExpiryInstant(day, zone), zone)).toBe(day);
      }
    }
    expect(shareExpiryDay(null, KL)).toBeNull();
  });

  it('a share stored before (23:59:59 UTC) shows the last day it works in the zone', () => {
    expect(shareExpiryDay('2027-01-15T23:59:59Z', KL)).toBe('2027-01-16');
    expect(shareExpiryDay('2027-01-15T23:59:59Z', LA)).toBe('2027-01-15');
    expect(shareExpiryDay('2027-01-15T23:59:59Z', 'UTC')).toBe('2027-01-15');
  });

  it('the last moment is one millisecond before the expiry', () => {
    expect(shareLastMoment('2026-12-31T16:00:00Z')).toBe('2026-12-31T15:59:59.999Z');
    expect(shareLastMoment('2027-01-15T23:59:59Z')).toBe('2027-01-15T23:59:58.999Z');
  });

  it('today is the day in the zone, not the UTC day', () => {
    expect(shareExpiryMinDay(KL, new Date('2026-11-18T20:00:00Z'))).toBe('2026-11-19');
    expect(shareExpiryMinDay(LA, new Date('2026-11-19T03:00:00Z'))).toBe('2026-11-18');
    expect(shareExpiryMinDay('UTC', new Date('2026-11-19T03:00:00Z'))).toBe('2026-11-19');
  });
});
