'use client';

/**
 * Loads the two-pane grade payload for an assignment via a service-bound
 * `ReviewSurfaceActions` (plan sprint-4/06 slice 2). Identity-agnostic — both
 * the staff and portal grade pages use it (each passes its own actions). The
 * page renders the SAME shared `ReviewTwoPaneView`.
 */
import { useEffect, useState } from 'react';
import type { ReviewSurfaceActions, ReviewTwoPane } from '@/types/portal-review';

export interface UseReviewTwoPaneResult {
  data: ReviewTwoPane | null;
  loading: boolean;
  error: string | null;
}

export function useReviewTwoPane(
  actions: ReviewSurfaceActions,
  assignmentId: string,
  /** Gate the load until the session token is ready (portal). */
  ready = true,
): UseReviewTwoPaneResult {
  const [data, setData] = useState<ReviewTwoPane | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !assignmentId) return;
    let active = true;
    setLoading(true);
    setError(null);
    actions
      .getTwoPane(assignmentId)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e: unknown) => {
        if (active) {
          setError(e instanceof Error ? e.message : 'Could not load this review.');
          setData(null);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // actions is memoized by the caller hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignmentId, ready]);

  return { data, loading, error };
}
