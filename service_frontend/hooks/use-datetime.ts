'use client';

import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import {
  browserTimeZone,
  dateKey,
  formatDate,
  formatDateTime,
  formatDmyDate,
  formatDmyDateTime,
  formatFxDate,
  formatFxDateTime,
  formatFxDayLine,
  formatFxRelative,
  formatFxTime,
  formatFxZoneLine,
  formatTime,
} from '@/lib/datetime';
import { useFx } from '@/hooks/use-fx';

export interface UseDatetimeReturn {
  /** Effective display timezone (user preference, else browser). */
  timeZone: string;
  formatDate: (iso: string | null | undefined) => string;
  formatDateTime: (iso: string | null | undefined) => string;
  formatTime: (iso: string | null | undefined) => string;
  /** "05/11/2026, 3:04 pm" */
  formatDmyDateTime: (iso: string | null | undefined) => string;
  /** "05/11/2026" */
  formatDmyDate: (iso: string | null | undefined) => string;
  /** Foundryx UIUX: "now", "5 min", "3 h", "Yesterday", "14 Nov" for lists
   *  and feeds; pair it with `formatDateTime` as the tooltip. */
  formatRelative: (iso: string | null | undefined) => string;
  /** Foundryx UIUX: the day line in a long feed ("Today", "Yesterday", "14 Nov 2026"). */
  formatDayLine: (iso: string | null | undefined) => string;
  /** Foundryx UIUX: the zone line under a time picker ("Kuala Lumpur time (GMT+8)"). */
  zoneLine: string;
}

/**
 * Session-aware datetime formatters (plan sprint-2/05) - bind the user's
 * timezone preference (`session.user.timezone`, IANA; null = browser tz) onto
 * the shared `lib/datetime.ts` family. Every component rendering a backend
 * timestamp goes through this hook.
 */
export function useDatetime(): UseDatetimeReturn {
  const { data: session } = useSession();
  const preferred = session?.user?.timezone ?? null;

  // Foundryx UIUX switch: while on, dates, moments and times use the
  // playbook's form ("14 Nov 2026, 2:14 pm", 12-hour clock). Off = today's.
  const fx = useFx();

  return useMemo(() => {
    const timeZone = preferred ?? browserTimeZone();
    const opts = { timeZone: preferred };
    return {
      timeZone,
      formatDate: (iso) => (fx ? formatFxDate(iso, opts) : formatDate(iso, opts)),
      formatDateTime: (iso) => (fx ? formatFxDateTime(iso, opts) : formatDateTime(iso, opts)),
      formatTime: (iso) => (fx ? formatFxTime(iso, opts) : formatTime(iso, opts)),
      formatDmyDateTime: (iso) => formatDmyDateTime(iso, { timeZone: preferred }),
      // A backend timestamp -> its calendar day in the viewer's zone -> 05/11/2026.
      formatDmyDate: (iso) => formatDmyDate(dateKey(iso, { timeZone: preferred })),
      formatRelative: (iso) => formatFxRelative(iso, opts),
      formatDayLine: (iso) => formatFxDayLine(iso, opts),
      zoneLine: formatFxZoneLine(timeZone),
    };
  }, [preferred, fx]);
}
