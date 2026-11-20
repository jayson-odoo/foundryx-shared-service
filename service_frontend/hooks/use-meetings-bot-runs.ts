'use client';

import { useCallback, useEffect, useState } from 'react';
import { meetingsService } from '@/services/meetings-service';
import type { MeetingsBotRun } from '@/types/meetings';

export interface UseMeetingsBotRuns {
  runs: MeetingsBotRun[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

/**
 * The tenant's bot runs over the last `days` days (S2 plan §6, AC-S2-12).
 *
 * Gated `meetings.settings.manage` on the backend: a run is tenant-wide ops
 * data, not the caller's own meeting.
 */
export function useMeetingsBotRuns(days = 7): UseMeetingsBotRuns {
  const [runs, setRuns] = useState<MeetingsBotRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuns(await meetingsService.listBotRuns(days));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load bot runs.');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { runs, loading, error, reload };
}
