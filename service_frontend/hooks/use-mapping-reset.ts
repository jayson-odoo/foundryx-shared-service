'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import { isMappingResetPreview } from '@/types/autocount';
import type { AutocountMappingResetPreview, AutocountMappingView } from '@/types/autocount';

export interface UseMappingResetResult {
  /** The dry-run diff, or `null` while loading/on a load error. */
  preview: AutocountMappingResetPreview | null;
  isLoading: boolean;
  /** The dry-run fetch's error message (e.g. the "no preset" 422) - a
   *  defensive state the ActionMenu gating normally prevents (AC-12-21),
   *  surfaced inline should it still happen (a stale `hasPreset` race). */
  loadError: string | null;
  isApplying: boolean;
  /** The apply's error message - the dialog stays open with this in place
   *  of the primary row (AC-12-23). */
  applyError: string | null;
  /** `POST .../mapping/reset-preset {dryRun: false}` - true on success
   *  (the caller's `onApplied` already ran). */
  apply: () => Promise<boolean>;
}

/**
 * One entity's mapping-reset preview + apply (AC-12-12/13/22/23). Fetches
 * the dry run the moment `open` flips true (never while closed - no
 * request until the operator actually opens the dialog), and re-fetches
 * every time it reopens. `onApplied` receives the fresh mapping view so the
 * caller can refresh its own draft/table.
 */
export function useMappingReset(
  companyId: string,
  entityType: string,
  open: boolean,
  onApplied: (view: AutocountMappingView) => void,
): UseMappingResetResult {
  const [preview, setPreview] = useState<AutocountMappingResetPreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPreview(null);
    setLoadError(null);
    setApplyError(null);
    setIsLoading(true);
    autocountService
      .resetMappingToPreset(companyId, entityType, { dryRun: true })
      .then((result) => {
        if (cancelled) return;
        if (isMappingResetPreview(result)) {
          setPreview(result);
        } else {
          setLoadError('That preview could not be read.');
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(error instanceof ApiError ? error.message : 'That preview could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, companyId, entityType]);

  const apply = useCallback(async (): Promise<boolean> => {
    setIsApplying(true);
    setApplyError(null);
    try {
      const result = await autocountService.resetMappingToPreset(companyId, entityType, { dryRun: false });
      if (isMappingResetPreview(result)) {
        setApplyError('That reset could not be applied.');
        return false;
      }
      onApplied(result);
      return true;
    } catch (error) {
      setApplyError(error instanceof ApiError ? error.message : 'That reset could not be applied.');
      return false;
    } finally {
      setIsApplying(false);
    }
  }, [companyId, entityType, onApplied]);

  return { preview, isLoading, loadError, isApplying, applyError, apply };
}
