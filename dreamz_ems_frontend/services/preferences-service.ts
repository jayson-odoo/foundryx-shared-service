/**
 * View-preferences service — per-user column prefs (order/width/visibility) by
 * view_key, persisted to the backend `user_view_preferences` table via
 * GET/PATCH /me/preferences/{view_key}. Failures degrade silently (prefs are
 * non-critical UX).
 */
import { apiFetch } from '@/lib/api-client';
import type { ViewPreferences } from '@/types/resource';

export interface PreferencesService {
  get(viewKey: string): Promise<ViewPreferences | null>;
  save(viewKey: string, prefs: ViewPreferences): Promise<void>;
}

export const preferencesService: PreferencesService = {
  async get(viewKey) {
    try {
      return await apiFetch<ViewPreferences | null>(`/me/preferences/${viewKey}`);
    } catch {
      return null;
    }
  },
  async save(viewKey, prefs) {
    try {
      await apiFetch<ViewPreferences>(`/me/preferences/${viewKey}`, {
        method: 'PATCH',
        body: JSON.stringify(prefs),
      });
    } catch {
      // non-fatal — prefs are best-effort
    }
  },
};
