'use client';

/**
 * S5 public idea-status page data (mirrors `use-public-share.ts`) - resolves
 * once on mount, no auth. A uniform 404 (unknown/malformed/draft token) sets
 * `notFound`; any other failure also degrades to not-found (a pre-auth page
 * never surfaces a raw error).
 */
import { useEffect, useState } from 'react';
import { publicIdeaStatusService } from '@/services/public-idea-status-service';
import type { PublicIdeaStatus } from '@/types/ideation';

export interface UsePublicIdeaStatus {
  view: PublicIdeaStatus | null;
  loading: boolean;
  notFound: boolean;
}

export function usePublicIdeaStatus(token: string): UsePublicIdeaStatus {
  const [view, setView] = useState<PublicIdeaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setNotFound(false);
      try {
        const v = await publicIdeaStatusService.resolve(token);
        if (cancelled) return;
        if (v === null) setNotFound(true);
        else setView(v);
      } catch {
        if (!cancelled) setNotFound(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { view, loading, notFound };
}
