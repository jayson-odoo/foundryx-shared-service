'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { browserTimeZone } from '@/lib/datetime';
import { profilePreferencesService } from '@/services/profile-preferences-service';

export interface UseTimezonePreferenceReturn {
  /** Stored preference (IANA) or null = browser tz. */
  timezone: string | null;
  /** The browser tz used while no preference is set. */
  browserTimeZone: string;
  isSaving: boolean;
  error: string | null;
  save: (timezone: string | null) => Promise<boolean>;
}

/**
 * Timezone preference state for My Account (plan sprint-2/05). Reads the
 * session value, saves through the service boundary, then refreshes the
 * session (jwt `update` branch re-pulls /auth/me - Phase B) with a local
 * optimistic value so the picker reflects the save immediately.
 */
export function useTimezonePreference(): UseTimezonePreferenceReturn {
  const { data: session, update } = useSession();
  // undefined = no local override yet (use the session value)
  const [override, setOverride] = useState<string | null | undefined>(undefined);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionTz = session?.user?.timezone ?? null;
  const timezone = override !== undefined ? override : sessionTz;

  const save = async (next: string | null): Promise<boolean> => {
    setIsSaving(true);
    setError(null);
    try {
      await profilePreferencesService.saveTimezone(next);
      setOverride(next);
    } catch {
      setError('Could not save your timezone - please try again.');
      setIsSaving(false);
      return false;
    }
    try {
      // Pull the fresh value into the session so useDatetime everywhere
      // re-renders timestamps in the new tz. A hiccup here is NOT a save
      // failure - the preference persisted; the session catches up on the
      // next refresh (review fix: don't report success as an error).
      await update();
    } catch {
      // best-effort
    }
    setIsSaving(false);
    return true;
  };

  return { timezone, browserTimeZone: browserTimeZone(), isSaving, error, save };
}
