'use client';

/**
 * One report's read (plan 30, AC-RPT-44) - refetches on workspace, report
 * key, filter or pagination change. Each renderer casts `rows`/`totals` to
 * its own concrete shape (see `types/omnichannel.ts` per-report row types).
 */
import { useEffect, useState } from 'react';
import { omnichannelReportService, type ReportQuery } from '@/services/omnichannel-report-service';
import type { ReportKey, ReportResponse } from '@/types/omnichannel';

export interface UseOmnichannelReportResult {
  report: ReportResponse | null;
  loading: boolean;
  error: boolean;
}

export function useOmnichannelReport(
  workspaceId: string | null,
  reportKey: ReportKey,
  query: ReportQuery,
): UseOmnichannelReportResult {
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!workspaceId) {
      setReport(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    omnichannelReportService
      .report(workspaceId, reportKey, query)
      .then((res) => !cancelled && setReport(res))
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, reportKey, JSON.stringify(query)]);

  return { report, loading, error };
}
