'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ImportJob } from '@/types/import';
import { importService } from '@/services/import-service';

const POLL_MS = 4000;
const IN_FLIGHT = new Set(['pending', 'validating', 'importing']);

/**
 * Recent import jobs for the Imports drawer (sprint-3/09 D9). Polls every 4s
 * while any job is in flight; stops when all settle (intelligent stop, mirrors
 * the Downloads drawer).
 */
export function useImportJobs(): {
  jobs: ImportJob[];
  refresh: () => Promise<void>;
  loading: boolean;
} {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await importService.list({ pageSize: 10 });
      setJobs(res.items);
    } catch {
      /* drawer degrades silently */
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
        if (cur.some((j) => IN_FLIGHT.has(j.status))) {
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

  return { jobs, refresh, loading };
}
