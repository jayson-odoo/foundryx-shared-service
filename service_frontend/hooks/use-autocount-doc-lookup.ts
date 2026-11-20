'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import {
  autocountDocLookupService,
  type AutocountDocLookupService,
} from '@/services/autocount-doc-lookup-service';
import type {
  DocLookupJob,
  DocLookupStartInput,
  DocLookupStored,
  DocLookupType,
} from '@/types/autocount-doc-lookup';

const TERMINAL: ReadonlyArray<DocLookupJob['status']> = ['done', 'failed', 'aborted'];

export function isTerminalLookup(job: DocLookupJob | null): boolean {
  return job !== null && TERMINAL.includes(job.status);
}

/** 250ms for the first second, then 1500ms - the preview-job cadence. */
export function defaultLookupPollDelay(elapsedMs: number): number {
  return elapsedMs < 1000 ? 250 : 1500;
}

/** The job id a `409 LOOKUP_IN_FLIGHT` names (the search blocking this company). */
export function blockingJobId(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const detail = e.detail as { jobId?: unknown } | undefined;
  return detail && typeof detail === 'object' && typeof detail.jobId === 'string' ? detail.jobId : null;
}

/** The backend's `{detail: {code, message}}` message, else the plain one. */
export function lookupErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = e.detail as { message?: unknown } | undefined;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
    return e.message;
  }
  return e instanceof Error ? e.message : 'The search failed.';
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── types ────────────────────────────────────────────────────────────────────

export interface UseDocLookupTypesResult {
  types: DocLookupType[];
  isLoading: boolean;
}

export function useDocLookupTypes(
  companyId: string | null,
  service: AutocountDocLookupService = autocountDocLookupService,
): UseDocLookupTypesResult {
  const [types, setTypes] = useState<DocLookupType[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    service
      .listTypes(companyId)
      .then((data) => {
        if (!cancelled) setTypes(data);
      })
      .catch(() => {
        if (!cancelled) setTypes([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, service]);

  return { types, isLoading };
}

// ── the search ───────────────────────────────────────────────────────────────

/**
 * `idle` -> `stored` (sightings shown, live search starting) -> `searching`
 * (job polling) -> `done` (the job ended: done / failed / aborted) or
 * `error` (a request itself failed - validation, no connection, network).
 */
export type DocLookupPhase = 'idle' | 'stored' | 'searching' | 'done' | 'error';

export interface UseDocLookupResult {
  phase: DocLookupPhase;
  stored: DocLookupStored | null;
  job: DocLookupJob | null;
  error: string | null;
  /** Set when a 409 named another running search for the same company. */
  blockingJob: string | null;
  stopping: boolean;
  search: (input: DocLookupStartInput) => Promise<void>;
  stop: () => Promise<void>;
  /** Stop the search named by `blockingJob`, then clear the error. */
  stopBlocking: () => Promise<void>;
  reset: () => void;
}

export interface UseDocLookupOptions {
  service?: AutocountDocLookupService;
  pollDelay?: (elapsedMs: number) => number;
}

export function useDocLookup(options: UseDocLookupOptions = {}): UseDocLookupResult {
  const service = options.service ?? autocountDocLookupService;
  const delayFor = options.pollDelay ?? defaultLookupPollDelay;
  const [phase, setPhase] = useState<DocLookupPhase>('idle');
  const [stored, setStored] = useState<DocLookupStored | null>(null);
  const [job, setJob] = useState<DocLookupJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blockingJob, setBlockingJob] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  // Every search / reset / unmount bumps the run id; a stale run's late
  // responses are dropped instead of landing in state.
  const runId = useRef(0);

  useEffect(
    () => () => {
      runId.current += 1;
    },
    [],
  );

  const search = useCallback(
    async (input: DocLookupStartInput) => {
      runId.current += 1;
      const mine = runId.current;
      const stale = () => runId.current !== mine;
      setPhase('stored');
      setStored(null);
      setJob(null);
      setError(null);
      setBlockingJob(null);
      setStopping(false);
      try {
        const sightings = await service.stored(input.companyId, input.docNo, input.docType);
        if (stale()) return;
        setStored(sightings);

        let current = await service.start(input);
        if (stale()) return;
        setJob(current);
        setPhase(isTerminalLookup(current) ? 'done' : 'searching');

        const startedAt = Date.now();
        while (!isTerminalLookup(current)) {
          await pause(delayFor(Date.now() - startedAt));
          if (stale()) return;
          try {
            current = await service.getJob(current.jobId);
          } catch {
            // One transient poll failure is retried once before giving up.
            await pause(delayFor(Date.now() - startedAt));
            if (stale()) return;
            current = await service.getJob(current.jobId);
          }
          if (stale()) return;
          setJob(current);
        }
        setPhase('done');
      } catch (e) {
        if (stale()) return;
        setError(lookupErrorMessage(e));
        setBlockingJob(blockingJobId(e));
        setPhase('error');
      } finally {
        if (!stale()) setStopping(false);
      }
    },
    [service, delayFor],
  );

  const stop = useCallback(async () => {
    if (!job || isTerminalLookup(job)) return;
    setStopping(true);
    try {
      setJob(await service.stop(job.jobId));
    } catch (e) {
      setError(lookupErrorMessage(e));
    }
  }, [job, service]);

  const stopBlocking = useCallback(async () => {
    if (!blockingJob) return;
    try {
      await service.stop(blockingJob);
      setBlockingJob(null);
      setError(null);
      setPhase('idle');
    } catch (e) {
      setError(lookupErrorMessage(e));
    }
  }, [blockingJob, service]);

  const reset = useCallback(() => {
    runId.current += 1;
    setPhase('idle');
    setStored(null);
    setJob(null);
    setError(null);
    setBlockingJob(null);
    setStopping(false);
  }, []);

  return { phase, stored, job, error, blockingJob, stopping, search, stop, stopBlocking, reset };
}
