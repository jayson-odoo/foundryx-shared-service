'use client';

import { useCallback, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type { AutocountPreview } from '@/types/autocount';

export interface UseAutocountPreviewResult {
  preview: AutocountPreview | null;
  isLoading: boolean;
  /** Set when the dry run itself failed (HTTP 502) — approval must be blocked. */
  error: string | null;
  /** True once a preview has been requested (drives whether to show the panel). */
  hasRun: boolean;
  /**
   * True only while a run failed — the overwrite gate must refuse approval while
   * the dry run cannot be completed (AC-14-20: never approve blind).
   */
  failed: boolean;
  run: () => Promise<void>;
}

/**
 * The dry-run preview behind the approval gate (AC-14-20/21). Fetches Sorento's
 * own rolled-back resolution — never a local reconstruction. A logging-sink
 * company returns a `previewable: false` shape; an unreachable consumer throws
 * (HTTP 502), which SETS `failed` so the surface disables Approve.
 */
export function useAutocountPreview(jobId: string): UseAutocountPreviewResult {
  const [preview, setPreview] = useState<AutocountPreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);

  const run = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await autocountService.preview(jobId);
      setPreview(res.preview);
    } catch (err) {
      // A failed dry run leaves no prediction and blocks approval — surface the
      // message and drop any stale prediction.
      setPreview(null);
      setError(
        err instanceof ApiError
          ? err.message
          : 'The dry run could not be completed.',
      );
    } finally {
      setHasRun(true);
      setIsLoading(false);
    }
  }, [jobId]);

  return {
    preview,
    isLoading,
    error,
    hasRun,
    failed: hasRun && error !== null,
    run,
  };
}
