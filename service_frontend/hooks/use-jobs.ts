'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { jobsService } from '@/services/jobs-service';
import { JOB_IN_FLIGHT, type Job, type JobListQuery } from '@/types/jobs';

const POLL_MS = 3000;

/**
 * Recent background jobs for the generic Jobs drawer / list (sprint-4/10).
 * Polls every 3s while any job is in flight (running/pending); stops when all
 * settle - mirrors `useImportJobs` (the Imports drawer). Filters are optional.
 */
export function useJobs(query: JobListQuery = {}): {
  jobs: Job[];
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep the latest query without re-subscribing the poll loop each render.
  const queryRef = useRef(query);
  queryRef.current = query;

  const refresh = useCallback(async () => {
    try {
      const res = await jobsService.listJobs(queryRef.current);
      setJobs(res.items);
    } catch {
      /* drawer/list degrades silently */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      if (!active) return;
      await refresh();
      if (!active) return;
      setJobs((cur) => {
        if (cur.some((j) => JOB_IN_FLIGHT.has(j.status))) {
          timer.current = setTimeout(tick, POLL_MS);
        }
        return cur;
      });
    };
    void tick();
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [refresh]);

  return { jobs, loading, refresh };
}
