'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ReportChart } from '@/components/platform/report-chart';
import { useOmnichannelReport } from '@/hooks/use-omnichannel-report';
import type { ConversationsReportTotals, ReportFilters } from '@/types/omnichannel';
import { ReportLoadingCard } from './report-loading-card';
import { useFx } from '@/hooks/use-fx';
import { FxBox } from '../../components/fx-report-parts';

/**
 * Conversations report (plan 30, AC-RPT-18/44) - opened/closed/reopened
 * series over the shared chart adapter, plus the range totals.
 */
export function ConversationsReport({ workspaceId, filters }: { workspaceId: string; filters: ReportFilters }) {
  const { report, loading, error, reload } = useOmnichannelReport(workspaceId, 'conversations', filters);
  const fx = useFx();

  // A failed load wins over the spinner in both looks, so it never spins forever.
  if (error) return <ReportLoadingCard errored onRetry={reload} />;
  if (loading || !report) return <ReportLoadingCard />;

  const totals = report.totals as ConversationsReportTotals;

  if (fx) {
    // One question, the totals as its answer above the chart.
    return (
      <FxBox title="Conversations opened, closed and reopened">
        <ReportChart
          buckets={report.buckets}
          series={report.series}
          fxTotals={{ opened: totals.opened, closed: totals.closed, reopened: totals.reopened }}
          emptyMessage="No conversations opened or closed in this range."
          className="h-72 w-full"
        />
      </FxBox>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap gap-6 py-5">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Opened</span>
            <span className="text-xl font-heading font-semibold">{totals.opened}</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Closed</span>
            <span className="text-xl font-heading font-semibold">{totals.closed}</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Reopened</span>
            <span className="text-xl font-heading font-semibold">{totals.reopened}</span>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Conversations over time</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportChart buckets={report.buckets} series={report.series} className="h-72 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
