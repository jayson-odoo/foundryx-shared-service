/**
 * Real profile-preferences service (plan sprint-2/05 Phase B) — PATCH
 * /me/preferences (perm-free self-scope, like the view-prefs sibling).
 */
import { apiFetch } from '@/lib/api-client';
import type { ProfilePreferencesService } from './profile-preferences-service';

export const realProfilePreferencesService: ProfilePreferencesService = {
  async saveTimezone(timezone) {
    await apiFetch('/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify({ timezone }),
    });
  },
};
