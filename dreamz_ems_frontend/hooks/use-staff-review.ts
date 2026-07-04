'use client';

/**
 * Staff review-surface hooks (plan sprint-4/06 slice 2, AC-06-46). Wrap the
 * staff review service (api-client) and expose loading/error/data + a memoized
 * `ReviewSurfaceActions`/`DecisionSurfaceActions` for the SAME shared components
 * the portal uses. Layering: UI → THESE hooks → service → api-client.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { staffReviewService } from '@/services/staff-review-service';
import type {
  DecisionItem,
  DecisionSurfaceActions,
  MyReview,
  ReviewSurfaceActions,
} from '@/types/portal-review';

interface ListState<T> {
  data: T[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useList<T>(loader: () => Promise<T[]>): ListState<T> {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    loader()
      .then((rows) => {
        if (active) setData(rows);
      })
      .catch((e: unknown) => {
        if (active) {
          setError(e instanceof Error ? e.message : 'Could not load.');
          setData([]);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  return { data, loading, error, reload };
}

export function useStaffReviewQueue(): ListState<MyReview> {
  return useList<MyReview>(() => staffReviewService.myReviews());
}

export function useStaffDecisions(): ListState<DecisionItem> {
  return useList<DecisionItem>(() => staffReviewService.decisions());
}

export function useStaffReviewActions(): ReviewSurfaceActions {
  return useMemo<ReviewSurfaceActions>(
    () => ({
      getTwoPane: (id) => staffReviewService.reviewTwoPane(id),
      saveDraft: (id, answers) => staffReviewService.saveReviewDraft(id, answers),
      submitReview: (id, answers) => staffReviewService.submitReview(id, answers),
    }),
    [],
  );
}

export function useStaffDecisionActions(): DecisionSurfaceActions {
  return useMemo<DecisionSurfaceActions>(
    () => ({
      decide: (groupId, decision, feedback) =>
        staffReviewService.decide(groupId, decision, feedback),
    }),
    [],
  );
}
