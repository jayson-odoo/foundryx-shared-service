'use client';

/**
 * Portal review-surface hooks (plan sprint-4/06 slice 2). Bind the PORTAL
 * session token onto the portal review service and expose loading/error/data +
 * a memoized `ReviewSurfaceActions`/`DecisionSurfaceActions` for the shared
 * components. Layering: portal UI → THESE hooks → service → portal-api-client.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import { portalReviewService } from '@/services/portal-review-service';
import { usePortalFilter } from '@/providers/portal-filter-provider';
import { activeContextScopeId } from '@/lib/portal-context';
import type { FormAnswers } from '@/types/forms';
import type {
  DecisionItem,
  DecisionSurfaceActions,
  MyReview,
  MySubmission,
  ReviewSurfaceActions,
  SubmitOption,
} from '@/types/portal-review';

function usePortalToken(): { token: string | null; status: string } {
  const { data: session, status } = useSession();
  const token =
    (session as unknown as { accessToken?: string } | null)?.accessToken ?? null;
  return { token, status };
}

/** True once the portal session has resolved (a Profile token is attachable).
 * Gate token-bound loads on this so a `null` token isn't sent as no-auth. */
export function usePortalSessionReady(): boolean {
  const { token, status } = usePortalToken();
  return status !== 'loading' && Boolean(token);
}

interface ListState<T> {
  data: T[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useList<T>(
  loader: (token: string | null, contextId: string | null) => Promise<T[]>,
): ListState<T> {
  const { token, status } = usePortalToken();
  // The global event-filter pill (AC-06-25) — narrows every surface to one
  // event. Re-fetch on a filter change so the surface DATA tracks the pill.
  const { activeContextKey } = usePortalFilter();
  const contextId = activeContextScopeId(activeContextKey);
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (status === 'loading') return;
    let active = true;
    setLoading(true);
    setError(null);
    loader(token, contextId)
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
    // loader is stable per surface; depend on session + active context + nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, status, contextId, nonce]);

  return { data, loading, error, reload };
}

export function usePortalSubmissions(): ListState<MySubmission> {
  return useList<MySubmission>((t, ctx) => portalReviewService.mySubmissions(t, ctx));
}

/** Configs the current Profile may submit to (AC-06-03) — drives the Submit
 * actions independent of any existing submissions. */
export function usePortalSubmitOptions(): ListState<SubmitOption> {
  return useList<SubmitOption>((t, ctx) => portalReviewService.submitOptions(t, ctx));
}

export function usePortalReviewQueue(): ListState<MyReview> {
  return useList<MyReview>((t, ctx) => portalReviewService.myReviews(t, ctx));
}

export function usePortalDecisions(): ListState<DecisionItem> {
  return useList<DecisionItem>((t, ctx) => portalReviewService.decisions(t, ctx));
}

/** The two-pane grade actions bound to the portal session token. */
export function usePortalReviewActions(): ReviewSurfaceActions {
  const { token } = usePortalToken();
  return useMemo<ReviewSurfaceActions>(
    () => ({
      getTwoPane: (id) => portalReviewService.reviewTwoPane(id, token),
      saveDraft: (id, answers) => portalReviewService.saveReviewDraft(id, answers, token),
      submitReview: (id, answers) => portalReviewService.submitReview(id, answers, token),
    }),
    [token],
  );
}

export function usePortalDecisionActions(): DecisionSurfaceActions {
  const { token } = usePortalToken();
  return useMemo<DecisionSurfaceActions>(
    () => ({
      decide: (groupId, decision, feedback) =>
        portalReviewService.decide(groupId, decision, feedback, token),
    }),
    [token],
  );
}

/** Submission write actions (submit / revise+resubmit), token-bound. */
export function usePortalSubmissionActions() {
  const { token } = usePortalToken();
  return useMemo(
    () => ({
      submitFormView: (configId: string) =>
        portalReviewService.submitFormView(configId, token),
      submit: (configId: string, answers: FormAnswers) =>
        portalReviewService.submit(configId, answers, token),
      revise: (groupId: string) => portalReviewService.revise(groupId, token),
      resubmit: (submissionId: string, answers: FormAnswers) =>
        portalReviewService.resubmit(submissionId, answers, token),
      submissionDetail: (groupId: string) =>
        portalReviewService.submissionDetail(groupId, token),
    }),
    [token],
  );
}
