'use client';

import { useEffect, useState } from 'react';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { BusinessRequirement } from '@/types/business-requirement';

export interface UseIdeaBusinessRequirementsResult {
  brs: BusinessRequirement[] | null;
  loading: boolean;
}

/** Loads the Business Requirements an idea feeds (reverse lineage, AC-BI-29c).
 * Confines the service call to the hook layer (UI → hook → service). */
export function useIdeaBusinessRequirements(
  ideaId: string,
  reloadToken = 0,
): UseIdeaBusinessRequirementsResult {
  const [brs, setBrs] = useState<BusinessRequirement[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBrs(null);
    businessRequirementService
      .listForIdea(ideaId)
      .then((rows) => {
        if (!cancelled) setBrs(rows);
      })
      .catch(() => {
        if (!cancelled) setBrs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ideaId, reloadToken]);

  return { brs, loading: brs === null };
}
