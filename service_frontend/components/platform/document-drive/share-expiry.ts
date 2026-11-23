/**
 * A share's expiry as the user's own calendar day.
 *
 * The backend stores one instant (`expiresAt`) and refuses the link from that
 * instant on (`share_service.py`: `expires_at <= now`). The dialogs hold a
 * day, `YYYY-MM-DD`, in the user's zone (`useDatetime().timeZone`: the zone
 * saved on the user's profile, else the browser's). A share set to expire on
 * day D works through the whole of day D there, so the instant sent is the
 * first moment of the next day in that zone (31 Dec 2026 in Kuala Lumpur is
 * `2026-12-31T16:00:00.000Z`).
 */
import { nextDayKey, startOfLocalDay } from '@/lib/date-filter';
import { dateKey, parseUtc, utcToZonedInputValue } from '@/lib/datetime';

/** The instant day `day` ends in `timeZone`, as an ISO UTC instant. */
export function shareExpiryInstant(day: string, timeZone: string): string {
  const wall = `${nextDayKey(day)}T00:00`;
  const first = new Date(startOfLocalDay(nextDayKey(day), timeZone));
  // `zonedTimeToUtc` reads the zone's offset once; on a day the clocks change
  // that offset can be the other side's, so read the result back and settle.
  const seen = utcToZonedInputValue(first.toISOString(), timeZone);
  const drift = seen ? Date.parse(`${wall}:00Z`) - Date.parse(`${seen}:00Z`) : 0;
  return new Date(first.getTime() + drift).toISOString();
}

/** The last moment a share still works: one millisecond before `expiresAt`. */
export function shareLastMoment(expiresAt: string): string {
  const at = parseUtc(expiresAt);
  return at ? new Date(at.getTime() - 1).toISOString() : expiresAt;
}

/** The last day a share works in `timeZone` (the day the date field shows). */
export function shareExpiryDay(expiresAt: string | null, timeZone: string): string | null {
  return expiresAt ? dateKey(shareLastMoment(expiresAt), { timeZone }) : null;
}

/** Today in `timeZone`: the earliest day an expiry can be set to. */
export function shareExpiryMinDay(timeZone: string, now: Date = new Date()): string {
  return dateKey(now, { timeZone }) ?? now.toISOString().slice(0, 10);
}
