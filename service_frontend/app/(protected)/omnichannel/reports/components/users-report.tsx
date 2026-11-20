'use client';

import { ResourceList } from '@/components/platform/resource-list';
import type { ReportFilters } from '@/types/omnichannel';
import { useUsersReportConfig } from './use-users-report-config';

/**
 * Users report (plan 30, AC-RPT-24/46) - an embedded `ResourceList` (server
 * pagination, the shell's Columns control), never a hand-rolled table.
 */
export function UsersReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const config = useUsersReportConfig(workspaceId, 'users', filters, false);
  return <ResourceList config={config} hideHeader />;
}
