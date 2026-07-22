'use client';

import { useEffect, useState } from 'react';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { BrTemplateVersion } from '@/types/business-requirement';

export interface UseBrVersionsResult {
  versions: BrTemplateVersion[] | null;
  loading: boolean;
}

/** Loads the BR's template version history. Confines the service call to the
 * hook layer (UI → hook → service). */
export function useBrVersions(brId: string): UseBrVersionsResult {
  const [versions, setVersions] = useState<BrTemplateVersion[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setVersions(null);
    businessRequirementService
      .listVersions(brId)
      .then((rows) => {
        if (!cancelled) setVersions(rows);
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [brId]);

  return { versions, loading: versions === null };
}
