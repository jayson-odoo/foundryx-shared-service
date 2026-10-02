'use client';

/**
 * The dashboard read (plan 30, AC-RPT-42) - one fetch per workspace + filter
 * change, tuned loading/error/success states with no backend (S0 mock).
 */
import { useEffect, useState } from 'react';
import { omnichannelReportService } from '@/services/omnichannel-report-service';
import type { DashboardResponse, ReportFilters } from '@/types/omnichannel';

export interface UseOmnichannelDashboardResult {
  dashboard: DashboardResponse | null;
  loading: boolean;
  error: boolean;
  reload: () => void;
}

export function useOmnichannelDashboard(
  workspaceId: string | null,
  filters: ReportFilters,
): UseOmnichannelDashboardResult {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!workspaceId) {
      setDashboard(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    omnichannelReportService
      .dashboard(workspaceId, filters)
      .then((res) => !cancelled && setDashboard(res))
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // filters is a plain, per-render-fresh object built from URL-synced
    // primitives - keying off its serialized shape avoids refetching on every
    // parent render while still refetching on any real change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, JSON.stringify(filters), reloadToken]);

  return { dashboard, loading, error, reload: () => setReloadToken((t) => t + 1) };
}
