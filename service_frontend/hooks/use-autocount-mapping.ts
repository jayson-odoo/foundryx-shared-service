'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountMappingView,
  AutocountMappingWriteRow,
} from '@/types/autocount';

export interface UseAutocountMappingResult {
  view: AutocountMappingView | null;
  isLoading: boolean;
  notFound: boolean;
  /** Last save error, surfaced inline (AC-15-44). Cleared on a fresh save. */
  saveError: string | null;
  isSaving: boolean;
  /**
   * Persist the deliverable rows (`PUT .../mapping`). Returns true on success;
   * on a server guard rejection (422) it returns false and populates
   * `saveError` — the shell stays in edit mode so the operator can fix it.
   */
  save: (rows: AutocountMappingWriteRow[]) => Promise<boolean>;
  reload: () => void;
}

/**
 * One entity's field-mapping view + save (AC-15-40/41). Components never fetch —
 * this is the hook boundary (`UI → hook → service → api-client`).
 */
export function useAutocountMapping(
  companyId: string,
  entityType: string,
): UseAutocountMappingResult {
  const [view, setView] = useState<AutocountMappingView | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    autocountService
      .getMapping(companyId, entityType)
      .then((v) => {
        if (cancelled) return;
        setView(v);
        setNotFound(false);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, entityType, reloadKey]);

  const save = useCallback(
    async (rows: AutocountMappingWriteRow[]): Promise<boolean> => {
      setIsSaving(true);
      setSaveError(null);
      try {
        const next = await autocountService.updateMapping(companyId, entityType, { rows });
        setView(next);
        return true;
      } catch (error) {
        setSaveError(
          error instanceof ApiError
            ? error.message
            : 'That mapping could not be saved.',
        );
        return false;
      } finally {
        setIsSaving(false);
      }
    },
    [companyId, entityType],
  );

  return { view, isLoading, notFound, saveError, isSaving, save, reload };
}
