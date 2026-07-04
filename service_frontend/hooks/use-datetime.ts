'use client';

import { useMemo } from 'react';
import { useSession } from 'next-auth/react';
import {
  browserTimeZone,
  formatDate,
  formatDateTime,
  formatTime,
} from '@/lib/datetime';

export interface UseDatetimeReturn {
  /** Effective display timezone (user preference, else browser). */
  timeZone: string;
  formatDate: (iso: string | null | undefined) => string;
  formatDateTime: (iso: string | null | undefined) => string;
  formatTime: (iso: string | null | undefined) => string;
}

/**
 * Session-aware datetime formatters (plan sprint-2/05) — bind the user's
 * timezone preference (`session.user.timezone`, IANA; null = browser tz) onto
 * the shared `lib/datetime.ts` family. Every component rendering a backend
 * timestamp goes through this hook.
 */
export function useDatetime(): UseDatetimeReturn {
  const { data: session } = useSession();
  const preferred = session?.user?.timezone ?? null;

  return useMemo(() => {
    const timeZone = preferred ?? browserTimeZone();
    return {
      timeZone,
      formatDate: (iso) => formatDate(iso, { timeZone: preferred }),
      formatDateTime: (iso) => formatDateTime(iso, { timeZone: preferred }),
      formatTime: (iso) => formatTime(iso, { timeZone: preferred }),
    };
  }, [preferred]);
}
