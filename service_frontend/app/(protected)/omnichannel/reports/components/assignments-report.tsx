'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ReportChart } from '@/components/platform/report-chart';
import { ResourceList } from '@/components/platform/resource-list';
import { useOmnichannelReport } from '@/hooks/use-omnichannel-report';
import type { AssignmentsReportTotals, ReportFilters } from '@/types/omnichannel';
import { ReportLoadingCard } from './report-loading-card';
import { useAssignmentLogConfig } from './use-assignment-log-config';

/**
 * Assignment log report (plan 30, AC-RPT-26/27/46) - the `assigned` series
 * plus totals from the shared report hook, and the paginated log as an
 * embedded `ResourceList` (never a hand-rolled table).
 */
export function AssignmentsReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const { report, loading, error } = useOmnichannelReport(workspaceId, 'assignments', filters);
  const config = useAssignmentLogConfig(workspaceId, filters);

  if (loading || !report) return <ReportLoadingCard />;
  if (error) return <ReportLoadingCard errored />;

  const totals = report.totals as AssignmentsReportTotals;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap gap-6 py-5">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Assigned</span>
            <span className="text-xl font-heading font-semibold">{totals.assigned}</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Unassigned</span>
            <span className="text-xl font-heading font-semibold">{totals.unassigned}</span>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Assignments over time</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportChart buckets={report.buckets} series={report.series} className="h-64 w-full" />
        </CardContent>
      </Card>
      <ResourceList config={config} hideHeader />
    </div>
  );
}
