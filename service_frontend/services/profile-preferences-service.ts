/**
 * Profile-preferences service (plan sprint-2/05) - user-level display
 * preferences, starting with the timezone (IANA name; null = browser tz).
 * Phase A binds the MOCK; Phase B swaps `profilePreferencesService` to the
 * real api-client impl in ONE line (bottom).
 *
 * The interface IS the backend contract (plan 05 §Backend):
 *   PATCH /me/preferences - auth'd, self-only; accepts { timezone }.
 */
import { realProfilePreferencesService } from './profile-preferences-service.real';

export interface ProfilePreferencesService {
  /** Persist the timezone preference; null clears it (= browser tz). */
  saveTimezone(timezone: string | null): Promise<void>;
}

// Phase B swap done - mock retained in profile-preferences-service.mock.ts.
export const profilePreferencesService: ProfilePreferencesService =
  realProfilePreferencesService;
