/**
 * Developer-logs retention settings (sprint-4/12 Slice 3, AC-DLC-21/23) — the
 * `/developers/logs/settings` page talks to the service through this hook, never
 * a direct fetch (UI → hook → service).
 */
'use client';

import { useCallback, useEffect, useState } from 'react';
import { integrationLogService } from '@/services/integration-log-service';
import type { IntegrationLogSettings } from '@/types/integration-logs';

export interface UseIntegrationLogSettings {
  settings: IntegrationLogSettings | null;
  isLoading: boolean;
  isSaving: boolean;
  /** Persist a new retention window; resolves the updated settings. */
  save(retentionDays: number): Promise<IntegrationLogSettings>;
}

export function useIntegrationLogSettings(): UseIntegrationLogSettings {
  const [settings, setSettings] = useState<IntegrationLogSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    integrationLogService
      .getSettings()
      .then((s) => {
        if (!cancelled) setSettings(s);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(async (retentionDays: number) => {
    setIsSaving(true);
    try {
      const updated = await integrationLogService.updateSettings(retentionDays);
      setSettings(updated);
      return updated;
    } finally {
      setIsSaving(false);
    }
  }, []);

  return { settings, isLoading, isSaving, save };
}
