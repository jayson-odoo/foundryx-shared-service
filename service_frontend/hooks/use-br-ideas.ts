'use client';

import { useEffect, useState } from 'react';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { Idea } from '@/types/ideation';

export interface UseBrIdeasResult {
  ideas: Idea[] | null;
  loading: boolean;
}

/** Loads the ideas linked to a BR (lineage). Confines the service call to the
 * hook layer (UI → hook → service). `reloadToken` bumps re-fetch. */
export function useBrIdeas(brId: string, reloadToken = 0): UseBrIdeasResult {
  const [ideas, setIdeas] = useState<Idea[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIdeas(null);
    businessRequirementService
      .listIdeas(brId)
      .then((rows) => {
        if (!cancelled) setIdeas(rows);
      })
      .catch(() => {
        if (!cancelled) setIdeas([]);
      });
    return () => {
      cancelled = true;
    };
  }, [brId, reloadToken]);

  return { ideas, loading: ideas === null };
}
