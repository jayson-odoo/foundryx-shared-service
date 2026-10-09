'use client';

import { ResourceList } from '@/components/platform/resource-list';
import type { ReportFilters } from '@/types/omnichannel';
import { useUsersReportConfig } from './use-users-report-config';

/**
 * Leaderboard report (plan 30, AC-RPT-25/46) - the users report's rows,
 * already ranked by the service, rendered with the rank column added.
 */
export function LeaderboardReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const config = useUsersReportConfig(workspaceId, 'leaderboard', filters, true);
  return <ResourceList config={config} hideHeader />;
}
