'use client';

/**
 * The workspace's report catalog (plan 30) - backs the report `SearchSelect`
 * and the team-dimension availability flag (D-A9-13: the `teamId`/`groupBy=
 * team` controls stay hidden until `dimensions.team.available` is true).
 */
import { useEffect, useState } from 'react';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { ReportMeta } from '@/types/omnichannel';

export interface UseReportMetaResult {
  meta: ReportMeta | null;
  loading: boolean;
  error: boolean;
}

export function useReportMeta(workspaceId: string | null): UseReportMetaResult {
  const [meta, setMeta] = useState<ReportMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    setMeta(null);
    setError(false);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    omnichannelReportService
      .meta(workspaceId)
      .then((res) => !cancelled && setMeta(res))
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return { meta, loading, error };
}
