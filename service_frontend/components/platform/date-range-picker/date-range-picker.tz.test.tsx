/**
 * S-6 (review round 1): `parseKey` used to build UTC-midnight Dates while
 * `react-day-picker` matches `selected`/`defaultMonth` against LOCAL-midnight
 * Dates (and `localDateKey` reads local components back out). West of UTC the
 * two disagreed by a day - `2026-03-01` highlighted Feb 28 and the popover
 * opened on the wrong month. This suite runs in `America/Los_Angeles` (UTC-8)
 * where the old code was wrong, and pins the round-trip identity.
 *
 * The TZ is set BEFORE the module is loaded, so the import is dynamic (a
 * static import would hoist above the assignment).
 */
const previousTz = process.env.TZ;
process.env.TZ = 'America/Los_Angeles';

import { afterAll, describe, expect, it } from 'vitest';

const { localDateKey, parseKey } = await import('./date-range-picker');

afterAll(() => {
  // Vitest isolates files by default, but restore anyway so a shared-worker
  // config can never inherit a west-of-UTC clock from this suite.
  if (previousTz === undefined) delete process.env.TZ;
  else process.env.TZ = previousTz;
});

describe('date key round-trip west of UTC', () => {
  it('actually runs in America/Los_Angeles (guards against a vacuous pass)', () => {
    // UTC-8 in March-before-DST / UTC-7 after: either way, never 0.
    expect(new Date(2026, 2, 1).getTimezoneOffset()).toBeGreaterThan(0);
  });

  it('localDateKey(parseKey(key)) === key', () => {
    for (const key of ['2026-03-01', '2026-01-01', '2026-12-31', '2026-03-08', '2026-11-01']) {
      expect(localDateKey(parseKey(key))).toBe(key);
    }
  });

  it('parseKey lands on the intended calendar day, not the one before', () => {
    const d = parseKey('2026-03-01');
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(2); // March
    expect(d.getDate()).toBe(1);
  });
});
