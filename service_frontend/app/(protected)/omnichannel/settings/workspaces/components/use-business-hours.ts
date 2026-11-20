'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { businessHoursService } from '@/services/business-hours-service';
import {
  BUSINESS_HOURS_WEEKDAYS,
  type BusinessHours,
  type BusinessHoursWindows,
} from '@/types/omnichannel';

/**
 * Business hours tab hook (plan 31 S6, AC-WFP-55/63) - `UI → hook → service →
 * api-client`. Mirrors `useAutocountEtlTask`'s save/fieldErrors shape.
 */

function emptyWindows(): BusinessHoursWindows {
  const result = {} as BusinessHoursWindows;
  for (const day of BUSINESS_HOURS_WEEKDAYS) result[day] = [];
  return result;
}

function readFieldErrors(detail: unknown): Record<string, string> {
  if (!detail || typeof detail !== 'object') return {};
  const bag = (detail as { fieldErrors?: unknown }).fieldErrors;
  if (!bag || typeof bag !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(bag as Record<string, unknown>)) {
    if (typeof value === 'string') out[key] = value;
  }
  return out;
}

export interface UseBusinessHoursResult {
  isLoading: boolean;
  /** Set when the initial GET failed - the tab renders a failure state with
   * no editable fields (nothing to Save over a schedule we never loaded). */
  loadError: string | null;
  timezone: string | null;
  windows: BusinessHoursWindows;
  isDirty: boolean;
  isSaving: boolean;
  saveError: string | null;
  fieldErrors: Record<string, string>;
  setTimezone: (tz: string) => void;
  setWindows: (windows: BusinessHoursWindows) => void;
  /** False (with `saveError`/`fieldErrors`) on a rejected save - the caller
   * (the workspace form's global Save) keeps edit mode open so the user can
   * fix the highlighted window. */
  save: () => Promise<boolean>;
  discard: () => void;
}

export function useBusinessHours(workspaceId: string | null): UseBusinessHoursResult {
  const [baseline, setBaseline] = useState<BusinessHours | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [timezone, setTimezoneState] = useState<string | null>(null);
  const [windows, setWindowsState] = useState<BusinessHoursWindows>(emptyWindows());
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!workspaceId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    businessHoursService
      .get(workspaceId)
      .then((loaded) => {
        if (cancelled) return;
        setBaseline(loaded);
        setTimezoneState(loaded.timezone);
        setWindowsState(loaded.windows);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Business hours could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const isDirty =
    baseline !== null &&
    (timezone !== baseline.timezone ||
      JSON.stringify(windows) !== JSON.stringify(baseline.windows));

  const setTimezone = useCallback((tz: string) => setTimezoneState(tz), []);
  const setWindows = useCallback((next: BusinessHoursWindows) => setWindowsState(next), []);

  const save = useCallback(async (): Promise<boolean> => {
    if (!workspaceId || !isDirty) return true;
    setIsSaving(true);
    setSaveError(null);
    setFieldErrors({});
    try {
      const saved = await businessHoursService.update(workspaceId, {
        timezone: timezone ?? '',
        windows,
      });
      setBaseline(saved);
      setTimezoneState(saved.timezone);
      setWindowsState(saved.windows);
      return true;
    } catch (error) {
      if (error instanceof ApiError) {
        setSaveError(error.message);
        setFieldErrors(readFieldErrors(error.detail));
      } else {
        setSaveError('Business hours could not be saved.');
      }
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [workspaceId, isDirty, timezone, windows]);

  const discard = useCallback(() => {
    if (!baseline) return;
    setTimezoneState(baseline.timezone);
    setWindowsState(baseline.windows);
    setSaveError(null);
    setFieldErrors({});
  }, [baseline]);

  return {
    isLoading,
    loadError,
    timezone,
    windows,
    isDirty,
    isSaving,
    saveError,
    fieldErrors,
    setTimezone,
    setWindows,
    save,
    discard,
  };
}
