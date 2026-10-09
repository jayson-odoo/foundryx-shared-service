'use client';

import { useCallback, useEffect, useState } from 'react';
import { meetingsService } from '@/services/meetings-service';
import type { MeetingsSettings, MeetingsSettingsInput } from '@/types/meetings';

export interface UseMeetingsSettings {
  settings: MeetingsSettings | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  reload: () => Promise<void>;
  save: (input: MeetingsSettingsInput) => Promise<MeetingsSettings>;
}

/** Tenant-wide meetings settings (S0 plan §4). Gated `meetings.settings.manage`. */
export function useMeetingsSettings(): UseMeetingsSettings {
  const [settings, setSettings] = useState<MeetingsSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSettings(await meetingsService.getSettings());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(async (input: MeetingsSettingsInput) => {
    setSaving(true);
    setError(null);
    try {
      const saved = await meetingsService.saveSettings(input);
      setSettings(saved);
      return saved;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save settings.');
      throw e;
    } finally {
      setSaving(false);
    }
  }, []);

  return { settings, loading, saving, error, reload, save };
}
