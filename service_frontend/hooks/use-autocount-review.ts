'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type { AutocountSyncJob } from '@/types/autocount';

/**
 * Why a decision is unavailable, phrased as a fact about the batch. Foolproof-UI:
 * an action that cannot succeed is disabled WITH a stated reason, never offered
 * and then rejected.
 */
const BLOCKED_REASON: Record<string, string> = {
  pending: 'This sync has not finished yet.',
  running: 'This sync is still running.',
  done: 'This batch has already been reviewed.',
  failed: 'This sync failed, so there is nothing to push.',
  aborted: 'This sync was aborted, so there is nothing to push.',
};

export interface UseAutocountReviewResult {
  job: AutocountSyncJob | null;
  /** Records in the batch (all statuses). */
  total: number;
  /** No-field-change records - collapsed in the staged list (AC-15-11). */
  noChangeCount: number;
  isLoading: boolean;
  notFound: boolean;
  isSubmitting: boolean;
  /** True only while the job sits in `needs_review` (AC-13-11). */
  canDecide: boolean;
  /** Set when `canDecide` is false - shown on the disabled buttons. */
  blockedReason: string | null;
  approve: () => Promise<void>;
  discard: () => Promise<void>;
  reload: () => void;
}

/**
 * The review surface's JOB-LEVEL data + decisions (AC-13-12). Approve pushes the
 * batch; Discard closes it without pushing. Both are idempotent server-side, and
 * both are only offered while the job is awaiting approval.
 *
 * The staged RECORDS are NOT loaded here - they render through their own
 * server-paginated Resource list (AC-15-10); this hook fetches only the job +
 * the batch counts (one small page).
 */
export function useAutocountReview(jobId: string): UseAutocountReviewResult {
  const [job, setJob] = useState<AutocountSyncJob | null>(null);
  const [total, setTotal] = useState(0);
  const [noChangeCount, setNoChangeCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    // One-record page: we need the job + counts, never the whole batch.
    autocountService
      .listStaged(jobId, { page: 0, pageSize: 1 })
      .then((res) => {
        if (cancelled) return;
        setJob(res.job);
        setTotal(res.total);
        setNoChangeCount(res.noChangeCount);
        setNotFound(false);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, reloadKey]);

  const canDecide = job?.status === 'needs_review';
  const blockedReason = useMemo(() => {
    if (canDecide || !job) return null;
    return BLOCKED_REASON[job.status] ?? 'This batch is not awaiting approval.';
  }, [canDecide, job]);

  const decide = useCallback(
    async (kind: 'approve' | 'discard') => {
      setIsSubmitting(true);
      try {
        if (kind === 'approve') {
          await autocountService.approve(jobId);
          toast.success('Batch approved.');
        } else {
          await autocountService.discard(jobId);
          toast.success('Batch discarded - nothing was pushed.');
        }
        setReloadKey((k) => k + 1);
      } catch (error) {
        const message =
          error instanceof ApiError ? error.message : 'That did not go through.';
        toast.error(message);
        // Re-read: a 409 means someone else already decided this batch, so the
        // surface must catch up rather than keep offering a stale action.
        setReloadKey((k) => k + 1);
      } finally {
        setIsSubmitting(false);
      }
    },
    [jobId],
  );

  const approve = useCallback(() => decide('approve'), [decide]);
  const discard = useCallback(() => decide('discard'), [decide]);

  return {
    job,
    total,
    noChangeCount,
    isLoading,
    notFound,
    isSubmitting,
    canDecide: Boolean(canDecide),
    blockedReason,
    approve,
    discard,
    reload,
  };
}
