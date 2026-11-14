'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { autocountService } from '@/services/autocount-service';
import type { AutocountPreviewJob, AutocountPreviewJobStartInput } from '@/types/autocount';

/**
 * The preview-job polling ENGINE (sprint-5/11, Group B; consolidated review
 * round 1, S2/S3/S6) - `pollPreviewJob` below is the ONE polling loop every
 * preview-job caller drives: this file's own `useAutocountPreviewJob`, AND
 * `use-autocount-etl.ts`'s `useEtlTaskPreview`/`useHttpPreview` (the Source
 * tab's Test and Review & Activate's Run preview). A fix to cleanup/backoff/
 * error-handling here fixes every caller at once - no more hand-rolled
 * `for(;;)` loops per hook.
 */

/**
 * The STANDING poll cadence (S2/S3/S6): 250ms for the first second, then
 * 1500ms - a 9-minute full-scope walk now costs roughly 360 GETs instead of
 * the ~2,700 a flat 200ms poll cost. A parameter (never a module constant
 * alone) so a Vitest suite can shrink it to a few ms without fake timers.
 */
export type PreviewJobPollDelay = (elapsedMs: number) => number;

export function defaultPreviewJobPollDelay(elapsedMs: number): number {
  return elapsedMs < 1000 ? 250 : 1500;
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface PollPreviewJobOptions {
  /** Checked before every poll AND before acting on its result - a stale
   * (superseded by a fresh start/attach/reset, or unmounted) run's poll
   * response is dropped silently rather than landing in state. */
  isStale: () => boolean;
  /** One settled poll's result. Return `true` to keep polling, `false` to
   * stop (a terminal status, or the caller's own decision - e.g. AC-11-23's
   * "this job belongs to the OTHER scope, leave it idle"). */
  onJob: (job: AutocountPreviewJob) => boolean;
  /** A poll itself failed (a 404 for a pruned job id, a network error) -
   * the loop always stops after this fires. The caller decides how to
   * surface it; this is what used to be an UNCAUGHT rejection in the old
   * hand-rolled `for(;;)` loops (S2/S3/S6's own bug: a pruned re-attach id
   * left the hook stuck in `loading` forever, permanently disabling the
   * Test button). */
  onError: (error: unknown) => void;
  delay?: PreviewJobPollDelay;
}

/**
 * A plain async function, never a hook itself - every caller drives it from
 * inside a `useCallback`/effect, not a component body, so this cannot use
 * `useState`/`useEffect` of its own.
 */
export async function pollPreviewJob(jobId: string, options: PollPreviewJobOptions): Promise<void> {
  const delayFor = options.delay ?? defaultPreviewJobPollDelay;
  const startedAt = Date.now();
  for (;;) {
    if (options.isStale()) return;
    let job: AutocountPreviewJob;
    try {
      job = await autocountService.getPreviewJob(jobId);
    } catch (e) {
      if (options.isStale()) return;
      options.onError(e);
      return;
    }
    if (options.isStale()) return;
    if (!options.onJob(job)) return;
    await pause(delayFor(Date.now() - startedAt));
  }
}

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
  pollMs: number = 200,
): UseAutocountPreviewJobResult {
  const [state, setState] = useState<UseAutocountPreviewJobState>({ phase: 'idle', job: null });
  const tokenRef = useRef(0);
  const cancellingRef = useRef(false);
  const activeJobIdRef = useRef<string | null>(null);

  // Cleanup on unmount - stops the loop's next `isStale()` check from acting
  // (any in-flight `getPreviewJob` await still resolves, but its result is
  // dropped rather than landing a `setState` on an unmounted component).
  useEffect(() => () => {
    tokenRef.current += 1;
  }, []);

  const phaseForStatus = useCallback((job: AutocountPreviewJob): PreviewJobPhase => {
    if (job.status === 'cancelled') return 'cancelled';
    if (job.status === 'failed') return 'failed';
    if (job.status === 'done') return 'done';
    // queued | running
    return cancellingRef.current ? 'cancelling' : job.status;
  }, []);

  const poll = useCallback(
    (jobId: string, token: number) => {
      void pollPreviewJob(jobId, {
        isStale: () => token !== tokenRef.current,
        delay: () => pollMs,
        onJob: (job) => {
          setState({ phase: phaseForStatus(job), job });
          return job.status === 'queued' || job.status === 'running';
        },
        onError: (e) => {
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
        },
      });
    },
    [phaseForStatus, pollMs],
  );

  const attach = useCallback(
    (jobId: string) => {
      const token = (tokenRef.current += 1);
      cancellingRef.current = false;
      activeJobIdRef.current = jobId;
      setState({ phase: 'queued', job: null });
      poll(jobId, token);
    },
    [poll],
  );

  const start = useCallback(
    async (input: AutocountPreviewJobStartInput) => {
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
    [poll],
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
    tokenRef.current += 1;
    cancellingRef.current = false;
    activeJobIdRef.current = null;
    setState({ phase: 'idle', job: null });
  }, []);

  const busy = state.phase === 'queued' || state.phase === 'running' || state.phase === 'cancelling';

  return { state, busy, start, cancel, attach, reset };
}
