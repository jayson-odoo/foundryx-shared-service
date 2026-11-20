'use client';

import { useEffect, useState } from 'react';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { Idea } from '@/types/ideation';

export interface UseIdeaMergedResult {
  /** `null` while loading, `[]` when nothing is merged into this idea. */
  merged: Idea[] | null;
}

/**
 * Loads the ideas merged into a survivor (issue #94, ideation round 2,
 * AC-94-25) - the "Merged from" tab's data source. Confines the service call
 * to the hook layer (UI -> hook -> service), same pattern as
 * `useIdeaBusinessRequirements`.
 */
export function useIdeaMerged(ideaId: string, reloadToken = 0): UseIdeaMergedResult {
  const { service } = useIdeationRuntime();
  const [merged, setMerged] = useState<Idea[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setMerged(null);
    if (!service.listMerged) {
      setMerged([]);
      return;
    }
    service
      .listMerged(ideaId)
      .then((rows) => {
        if (!cancelled) setMerged(rows);
      })
      .catch(() => {
        if (!cancelled) setMerged([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ideaId, reloadToken, service]);

  return { merged };
}
