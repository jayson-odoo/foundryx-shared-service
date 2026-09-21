'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type { AutocountPreviewJob, AutocountPreviewJobStartInput } from '@/types/autocount';

/**
 * The preview-job polling engine (sprint-5/11, Group B) - the ONE hook both
 * the Source tab's Test and Review & Activate's Run preview drive (D5: one
 * job kind, one progress UI, one cancel path). `UI -> hook -> service ->
 * api-client`; this hook never calls `fetch`/`axios` directly.
 *
 * Poll cadence is short and deterministic (no fake timers needed) so a
 * mock-driven UI settles in well under a second - the mock's own job ticks
 * land roughly every 60ms.
 */
const DEFAULT_POLL_MS = 200;

/**
 * `cancelling` is a CLIENT-side phase (AC-11-27's "cancel control"): the
 * operator clicked Cancel, the server-shaped job has not yet reported the
 * terminal `cancelled` status. `idle` is "never started / `reset()`".
 */
export type PreviewJobPhase =
  | 'idle'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'cancelled'
  | 'failed'
  | 'done';

export interface UseAutocountPreviewJobState {
  phase: PreviewJobPhase;
  /** Null only while `phase === 'idle'` or before the first poll response
   * lands. */
  job: AutocountPreviewJob | null;
}

export interface UseAutocountPreviewJobResult {
  state: UseAutocountPreviewJobState;
  /** True while queued/running/cancelling - both Test and Run preview
   * disable on this (AC-11-27's "stay disabled while their own job is in
   * flight", AC-11-23's one-preview-per-task). */
  busy: boolean;
  /** Start a job. Never throws - a start failure lands in `state` as
   * `failed`, mirroring the synchronous routes' own error surfacing. */
  start: (input: AutocountPreviewJobStartInput) => Promise<void>;
  /** Cooperative cancel - a no-op against an idle/already-terminal job
   * (AC-11-24: "never a 409 the UI has to explain"). */
  cancel: () => Promise<void>;
  /** Re-attach to an in-flight job id after a remount/reload (AC-11-23/27),
   * e.g. `task.previewJobId`. */
  attach: (jobId: string) => void;
  reset: () => void;
}

export function useAutocountPreviewJob(
  pollMs: number = DEFAULT_POLL_MS,
): UseAutocountPreviewJobResult {
  const [state, setState] = useState<UseAutocountPreviewJobState>({ phase: 'idle', job: null });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tokenRef = useRef(0);
  const cancellingRef = useRef(false);
  const activeJobIdRef = useRef<string | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  const phaseForStatus = useCallback((job: AutocountPreviewJob): PreviewJobPhase => {
    if (job.status === 'cancelled') return 'cancelled';
    if (job.status === 'failed') return 'failed';
    if (job.status === 'done') return 'done';
    // queued | running
    return cancellingRef.current ? 'cancelling' : job.status;
  }, []);

  const poll = useCallback(
    (jobId: string, token: number) => {
      autocountService
        .getPreviewJob(jobId)
        .then((job) => {
          if (token !== tokenRef.current) return;
          setState({ phase: phaseForStatus(job), job });
          if (job.status === 'queued' || job.status === 'running') {
            timerRef.current = setTimeout(() => poll(jobId, token), pollMs);
          }
        })
        .catch((e: unknown) => {
          if (token !== tokenRef.current) return;
          setState((prev) => ({
            phase: 'failed',
            job: prev.job
              ? {
                  ...prev.job,
                  status: 'failed',
                  error: e instanceof ApiError ? e.message : 'The preview could not be checked.',
                }
              : null,
          }));
        });
    },
    [phaseForStatus, pollMs],
  );

  const attach = useCallback(
    (jobId: string) => {
      clearTimer();
      const token = (tokenRef.current += 1);
      cancellingRef.current = false;
      activeJobIdRef.current = jobId;
      setState({ phase: 'queued', job: null });
      poll(jobId, token);
    },
    [clearTimer, poll],
  );

  const start = useCallback(
    async (input: AutocountPreviewJobStartInput) => {
      clearTimer();
      const token = (tokenRef.current += 1);
      cancellingRef.current = false;
      activeJobIdRef.current = null;
      setState({ phase: 'queued', job: null });
      try {
        const started = await autocountService.startPreviewJob(input);
        if (token !== tokenRef.current) return;
        activeJobIdRef.current = started.jobId;
        poll(started.jobId, token);
      } catch (e) {
        if (token !== tokenRef.current) return;
        setState({
          phase: 'failed',
          job: {
            id: '',
            scope: input.scope,
            status: 'failed',
            progress: null,
            result: null,
            error: e instanceof ApiError ? e.message : 'The preview could not be started.',
            taskError: null,
            createdAt: null,
          },
        });
      }
    },
    [clearTimer, poll],
  );

  const cancel = useCallback(async () => {
    const jobId = activeJobIdRef.current;
    if (!jobId) return;
    if (state.phase !== 'queued' && state.phase !== 'running') return;
    cancellingRef.current = true;
    setState((prev) => ({ ...prev, phase: 'cancelling' }));
    try {
      await autocountService.cancelPreviewJob(jobId);
    } catch {
      // The next poll tick is the authority either way - a transient cancel
      // failure never strands the UI in "cancelling" forever.
    }
  }, [state.phase]);

  const reset = useCallback(() => {
    clearTimer();
    tokenRef.current += 1;
    cancellingRef.current = false;
    activeJobIdRef.current = null;
    setState({ phase: 'idle', job: null });
  }, [clearTimer]);

  const busy = state.phase === 'queued' || state.phase === 'running' || state.phase === 'cancelling';

  return { state, busy, start, cancel, attach, reset };
}
