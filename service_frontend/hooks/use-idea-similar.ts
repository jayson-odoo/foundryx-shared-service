'use client';

import { useCallback, useEffect, useState } from 'react';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { Idea } from '@/types/ideation';

export type SimilarState =
  | { status: 'loading' }
  | { status: 'ready'; ideas: Idea[] }
  | { status: 'unavailable' };

export interface UseIdeaSimilarResult {
  state: SimilarState;
  /** Ask again (the AI was unavailable, or the list changed after a merge). */
  retry: () => void;
}

/**
 * AI-ranked similar ideas for the Similar ideas tab (plan 20, AC-20-23). A
 * failed request or `available: false` both resolve to `unavailable` (never a
 * spinner that cannot end); `retry` re-asks. UI -> hook -> service.
 */
export function useIdeaSimilar(ideaId: string): UseIdeaSimilarResult {
  const { service } = useIdeationRuntime();
  const [state, setState] = useState<SimilarState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    if (!service.similar) {
      setState({ status: 'unavailable' });
      return;
    }
    service
      .similar(ideaId)
      .then((res) => {
        if (cancelled) return;
        setState(res.available ? { status: 'ready', ideas: res.ideas } : { status: 'unavailable' });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'unavailable' });
      });
    return () => {
      cancelled = true;
    };
  }, [ideaId, attempt, service]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
