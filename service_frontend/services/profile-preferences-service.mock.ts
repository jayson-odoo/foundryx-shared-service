/**
 * Mock profile-preferences service (plan sprint-2/05 Phase A) - in-memory so
 * the My Account timezone picker is tunable with no backend running.
 */
import type { ProfilePreferencesService } from './profile-preferences-service';

export const mockProfilePreferencesService: ProfilePreferencesService = {
  async saveTimezone() {
    await new Promise((r) => setTimeout(r, 300));
  },
};
