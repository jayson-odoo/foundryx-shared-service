'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  omnichannelSettingsService,
  type OmnichannelSettings,
  type OmnichannelSettingsUpdate,
} from '@/services/omnichannel-settings-service';

export interface UseOmnichannelSettings {
  settings: OmnichannelSettings | null;
  loading: boolean;
  error: string | null;
  saving: boolean;
  /** Persist per-type overrides; resolves with the refreshed settings. */
  save: (overrides: OmnichannelSettingsUpdate) => Promise<OmnichannelSettings>;
  /** Re-fetch the current scope. */
  reload: () => Promise<void>;
}

/**
 * Loads + persists the omnichannel media-caps settings for a scope (a workspace
 * id, or the tenant default when omitted). The page reads settings ONLY through
 * this hook — the UI never touches the service/api-client directly.
 */
export function useOmnichannelSettings(workspaceId?: string | null): UseOmnichannelSettings {
  const [settings, setSettings] = useState<OmnichannelSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSettings(await omnichannelSettingsService.get(workspaceId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load media settings.');
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(
    async (overrides: OmnichannelSettingsUpdate) => {
      setSaving(true);
      setError(null);
      try {
        const next = await omnichannelSettingsService.update(overrides, workspaceId);
        setSettings(next);
        return next;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not save media settings.');
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [workspaceId],
  );

  return { settings, loading, error, saving, save, reload };
}
